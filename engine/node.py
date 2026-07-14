"""
Meeting Node — Per-Sub-Agent FastAPI Process for Technical Spike Meetings.

Each sub-agent runs as an independent process with its own LLM model and persona.
LLM calls go through LiteLLM which supports Gemini, Bedrock, OpenAI, etc.

Endpoints:
    /health           — liveness check
    /meeting_turn     — produce a structured meeting message (COMMENT, AGREE, etc.)
    /facilitate       — facilitator-only: decide who speaks next
    /relevance_check  — evaluate a nomination and accept or pass
"""

import sys
import os
import json
import uuid
import asyncio
import logging
import argparse
from datetime import datetime, timezone
from typing import Any, Optional

import litellm
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from engine.shared_memory import SharedMemory
from engine.agent_tools import (
    build_litellm_tools,
    execute_tool,
    set_reference_context_dir,
)
from engine.runtime import ssl_verify_enabled

logger = logging.getLogger("meeting_node")
app = FastAPI()
mem = SharedMemory()

# ── Mutable per-process state (set in __main__) ───────────────────────────

agent_id: str = "unknown"
agent_soul: str = ""
agent_model: str = "gemini/gemini-2.5-flash-preview-04-17"
agent_output_dir: str = ""
system_prompt_text: str = ""
model_temperature: float = 0.5
model_max_tokens: int = 800
meeting_rules: list[str] = []
agent_skills: list[str] = []

MAX_TOOL_ROUNDS = 6

_DEFAULT_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "message_schemas.json")
MESSAGE_SCHEMAS: dict[str, Any] = {}


def _load_schemas(path: str) -> None:
    global MESSAGE_SCHEMAS
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
            MESSAGE_SCHEMAS = {k: v for k, v in raw.items() if not k.startswith("_")}


_load_schemas(_DEFAULT_SCHEMA_PATH)

litellm.drop_params = True
litellm.ssl_verify = ssl_verify_enabled()


# ── Request / Response Models ─────────────────────────────────────────────


class MeetingTurnRequest(BaseModel):
    context_ref: str
    meeting_id: str
    phase: int
    directed_prompt: Optional[str] = None
    expected_message_type: Optional[str] = None


class FacilitateRequest(BaseModel):
    context_ref: str
    meeting_id: str
    elapsed_seconds: float
    time_limit_seconds: float
    speaker_history: list[str] = []
    silent_agents: list[str] = []
    participant_ids: list[str] = []
    author_id: str = ""
    proposal_sections: list[str] = []


class RelevanceCheckRequest(BaseModel):
    context_ref: str
    meeting_id: str
    nomination_context: str


class MeetingTurnResponse(BaseModel):
    status: str
    agent_id: str
    message_type: Optional[str] = None
    content: Optional[dict[str, Any]] = None
    content_length: int = 0


class FacilitateResponse(BaseModel):
    status: str
    decision: str
    targets: list[str] = []
    context: str = ""
    message: str = ""


class RelevanceCheckResponse(BaseModel):
    status: str
    agent_id: str
    decision: str  # ACCEPT or PASS
    reason: str = ""


# ── LiteLLM Completion ────────────────────────────────────────────────────


async def call_llm(
    system: str, user_prompt: str, temperature: float, max_tokens: int
) -> str:
    if "gemini-3" in agent_model and temperature < 1.0:
        temperature = 1.0
    tools = build_litellm_tools(agent_skills)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_prompt},
    ]

    for attempt in range(3):
        try:
            # Pass a fresh copy each attempt: _completion_with_tools appends the
            # assistant tool_calls message and tool results as it goes, and a
            # failure mid-round (e.g. malformed tool args) would otherwise leave
            # a dangling tool_calls entry that makes every later retry a 400.
            raw = await _completion_with_tools(
                list(messages), temperature, max_tokens, tools
            )
            if raw and len(raw.strip()) > 10:
                return raw.strip()
            logger.warning(f"Attempt {attempt + 1}: short response ({len(raw)} chars)")
        except Exception as e:
            logger.error(f"LLM error (attempt {attempt + 1}): {e}")
            if attempt < 2:
                await asyncio.sleep(2 * (attempt + 1))

    return ""


async def _completion_with_tools(
    messages: list[dict[str, Any]],
    temperature: float,
    max_tokens: int,
    tools: list[dict[str, Any]] | None,
) -> str:
    for tool_round in range(MAX_TOOL_ROUNDS + 1):
        kwargs: dict[str, Any] = {
            "model": agent_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = tools

        resp = await litellm.acompletion(**kwargs)
        choice = resp.choices[0]
        msg = choice.message

        if not msg.tool_calls:
            return msg.content or ""

        messages.append(msg.model_dump())

        for tc in msg.tool_calls:
            tool_name = tc.function.name
            try:
                tool_input = (
                    json.loads(tc.function.arguments) if tc.function.arguments else {}
                )
            except (json.JSONDecodeError, TypeError):
                # Truncated/invalid tool args (common when max_tokens cuts off
                # mid-call). Answer the tool_call with an error result so the
                # message sequence stays valid instead of raising.
                logger.warning(
                    f"Malformed tool arguments for {tool_name}: {tc.function.arguments!r}"
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": f"Error: could not parse arguments for tool '{tool_name}'.",
                    }
                )
                continue
            logger.info(
                f"Tool call [{tool_round + 1}/{MAX_TOOL_ROUNDS}]: {tool_name}({tool_input})"
            )
            result_text = execute_tool(tool_name, tool_input)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_text,
                }
            )

    logger.warning("Max tool rounds exceeded, returning last response")
    return ""


def _summarize_proposal_for_discussion(
    parsed: dict[str, Any], agent_id: str, meeting_id: str
) -> dict[str, Any]:
    """Convert a Phase-2 PROPOSAL_* message into a short COMMENT summary.

    The spike document and feedback fields come straight from the LLM and may be
    strings, lists, or dicts, so every access here tolerates the wrong shape
    (a bare-string spike_document previously raised AttributeError on doc.get).
    """
    summary_points: list[str] = []
    doc = parsed.get("updated_spike_document") or parsed.get("spike_document") or {}
    if not isinstance(doc, dict):
        doc = {}
    feedback = parsed.get("feedback_addressed")
    if feedback:
        if isinstance(feedback, dict):
            for _key, val in feedback.items():
                if isinstance(val, list):
                    summary_points.extend(val[:3])
                elif isinstance(val, str):
                    summary_points.append(val)
        elif isinstance(feedback, list):
            summary_points.extend(feedback[:5])
    if not summary_points:
        for key in ("proposed_solution", "problem_statement"):
            val = doc.get(key, "")
            if val and isinstance(val, str):
                summary_points.append(f"{key}: {val[:200]}")
                break
    if not summary_points:
        summary_points = [
            "Acknowledged feedback. Will incorporate in revised proposal."
        ]
    return {
        "message_type": "COMMENT",
        "from_agent": agent_id,
        "id": parsed.get("id", str(uuid.uuid4())),
        "timestamp": parsed.get("timestamp", datetime.now(timezone.utc).isoformat()),
        "meeting_id": meeting_id,
        "points": summary_points,
    }


def _parse_json_response(raw: str) -> dict[str, Any]:
    """Extract JSON from LLM response, handling markdown fences and nesting."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    for candidate in (text, raw.strip()):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start != -1 and end != -1:
            try:
                return json.loads(candidate[start : end + 1])
            except json.JSONDecodeError:
                pass

    return {}


_MESSAGE_TYPE_KEYS = {
    "COMMENT",
    "CHANGE_REQUEST",
    "DISAGREE",
    "AGREE",
    "PROPOSAL_SUBMISSION",
    "PROPOSAL_REVISION",
    "ARCHITECT_APPROVAL",
    "LEADERSHIP_DECISION",
    "MEETING_NOTES",
}


def _unwrap_content_object(parsed: dict[str, Any]) -> dict[str, Any]:
    """Unwrap LLM responses that nest the real payload inside a wrapper key.

    Handles two patterns:
      1. {"content": {"message_type": ..., ...}}
      2. {"CHANGE_REQUEST": {"message_type": "CHANGE_REQUEST", "changes": [...]}}
    """
    if not isinstance(parsed, dict):
        return parsed

    for key in list(parsed.keys()):
        if key in _MESSAGE_TYPE_KEYS:
            inner = parsed[key]
            if isinstance(inner, dict) and inner.get("message_type"):
                return inner

    content_val = parsed.get("content")
    if isinstance(content_val, dict) and content_val.get("message_type"):
        return content_val

    return parsed


def _extract_nested_json_from_points(
    parsed: dict[str, Any], expected_type: str
) -> dict[str, Any] | None:
    """If the LLM wrapped a structured message type inside a points array, extract it."""
    points = parsed.get("points", [])
    if not isinstance(points, list):
        return None
    for item in points:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        if not text.startswith("{"):
            start = text.find("{")
            if start == -1:
                continue
            text = text[start:]
        try:
            nested = json.loads(text)
            if isinstance(nested, dict) and nested.get("message_type"):
                return nested
        except (json.JSONDecodeError, TypeError):
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1:
                try:
                    nested = json.loads(text[start : end + 1])
                    if isinstance(nested, dict) and nested.get("message_type"):
                        return nested
                except (json.JSONDecodeError, TypeError):
                    pass
    return None


REQUIRED_FIELDS: dict[str, list[str]] = {
    "PROPOSAL_SUBMISSION": ["message_type"],
    "COMMENT": ["message_type"],
    "AGREE": ["message_type"],
    "DISAGREE": ["message_type"],
    "CHANGE_REQUEST": ["message_type"],
    "PROPOSAL_REVISION": ["message_type"],
    "ARCHITECT_APPROVAL": ["message_type", "decision"],
    "LEADERSHIP_DECISION": ["message_type", "decision"],
    "MEETING_NOTES": ["message_type"],
}

FIELD_DEFAULTS: dict[str, dict] = {
    "PROPOSAL_REVISION": {"feedback_addressed": []},
    "MEETING_NOTES": {"executive_summary": "", "decisions": [], "audit_trail": []},
}


def _normalize_field_aliases(msg: dict) -> None:
    """Normalize common LLM field name variations to canonical names."""
    msg_type = msg.get("message_type", "")
    if (
        msg_type == "PROPOSAL_REVISION"
        and "spike_document" in msg
        and "updated_spike_document" not in msg
    ):
        msg["updated_spike_document"] = msg.pop("spike_document")
    if msg_type == "CHANGE_REQUEST":
        if "change_requests" in msg and "changes" not in msg:
            msg["changes"] = msg.pop("change_requests")
        if "required_changes" in msg and "changes" not in msg:
            msg["changes"] = msg.pop("required_changes")


def _validate_and_fill(msg: dict, expected_type: str | None = None) -> bool:
    _normalize_field_aliases(msg)
    msg_type = msg.get("message_type", expected_type or "")
    required = REQUIRED_FIELDS.get(msg_type, [])
    if not all(msg.get(f) for f in required):
        return False
    for field, default in FIELD_DEFAULTS.get(msg_type, {}).items():
        msg.setdefault(field, default)
    return True


# ── Transcript helpers ────────────────────────────────────────────────────


async def _read_transcript(context_ref: str) -> list[dict]:
    data = await mem.get_context_ref(context_ref)
    if not data:
        return []
    return data.get("transcript", [])


async def _read_handbook(context_ref: str) -> str:
    data = await mem.get_context_ref(context_ref)
    if not data:
        return ""
    return data.get("domain_handbook", "")


async def _read_context_dir(context_ref: str) -> str:
    data = await mem.get_context_ref(context_ref)
    if not data:
        return ""
    return data.get("context_dir", "")


async def _append_to_transcript(context_ref: str, entry: dict) -> None:
    data = await mem.get_context_ref(context_ref)
    if not data:
        data = {"transcript": []}
    data.setdefault("transcript", []).append(entry)
    parts = context_ref.split(":")
    await mem.set(parts[0], ":".join(parts[1:]), data)


def _format_transcript_for_prompt(transcript: list[dict]) -> str:
    lines: list[str] = []
    for entry in transcript:
        speaker = entry.get("from_agent") or entry.get("name", "system")
        msg_type = entry.get("message_type", "MESSAGE")
        content = entry.get("content", "")
        if isinstance(content, dict):
            content = json.dumps(content, indent=2)
        lines.append(f"[{speaker}] ({msg_type}): {content}")
    return "\n\n".join(lines)


def _write_history(phase: int, msg_type: str, content: str) -> None:
    try:
        os.makedirs(agent_output_dir, exist_ok=True)
        path = os.path.join(agent_output_dir, "history.md")
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"### Phase {phase} — {msg_type} ({ts})\n\n")
            f.write(f"**Model:** `{agent_model}`\n\n")
            f.write(f"**Response:**\n{content}\n\n---\n\n")
    except Exception as e:
        logger.error(f"Failed to write history: {e}")


# ── Endpoints ─────────────────────────────────────────────────────────────


@app.get("/health")
async def health():
    return {"status": "online", "agent_id": agent_id, "model": agent_model}


@app.post("/meeting_turn", response_model=MeetingTurnResponse)
async def meeting_turn(req: MeetingTurnRequest):
    logger.info(
        f"Meeting turn: phase={req.phase}, expected={req.expected_message_type}"
    )

    transcript = await _read_transcript(req.context_ref)
    transcript_text = _format_transcript_for_prompt(transcript)
    handbook = await _read_handbook(req.context_ref)

    ctx_dir = await _read_context_dir(req.context_ref)
    if ctx_dir:
        set_reference_context_dir(ctx_dir)

    rules_text = ""
    if meeting_rules:
        rules_text = "\nMEETING RULES:\n- " + "\n- ".join(meeting_rules)

    has_tools = build_litellm_tools(agent_skills) is not None
    handbook_block = ""
    if handbook:
        tool_hint = ""
        if has_tools:
            tool_hint = (
                "\n\nIMPORTANT — You MUST use your tools before responding:"
                "\n1. read_reference_file: Read EACH available reference document listed above. "
                "Base your arguments on specific facts and evidence from these documents."
                "\n2. web_search: Search for real-world external examples, case studies, or "
                "industry precedents that support or challenge the discussion. "
                "For example, search for how other companies handled similar situations."
                "\nDo NOT fabricate statistics or evidence. Either cite reference documents or web search results."
            )
        handbook_block = (
            f"REFERENCE HANDBOOK — Available reference documents:\n\n"
            f"{handbook}\n\n"
            f"END OF HANDBOOK{tool_hint}\n\n"
        )

    full_system = system_prompt_text.replace("${meeting_id}", req.meeting_id).replace(
        "${current_phase}", str(req.phase)
    )

    directed = req.directed_prompt or ""
    if req.expected_message_type:
        schema = MESSAGE_SCHEMAS.get(req.expected_message_type)
        if schema:
            directed += (
                f"\n\nYou MUST respond with EXACTLY this JSON structure:\n"
                f"{json.dumps(schema, indent=2)}\n"
                f"Fill in real values. Do NOT add extra fields."
            )
        else:
            directed += f'\n\nYou MUST respond with a JSON object where message_type = "{req.expected_message_type}".'
    else:
        phase2_types = ["COMMENT", "CHANGE_REQUEST", "DISAGREE", "AGREE"]
        phase2_blocks = []
        for t in phase2_types:
            schema = MESSAGE_SCHEMAS.get(t)
            if schema:
                phase2_blocks.append(f"### {t}\n{json.dumps(schema, indent=2)}")
        if phase2_blocks:
            directed += (
                "\n\nChoose ONE message type below and respond with EXACTLY that JSON structure. "
                "Do NOT wrap it in another object. Output ONLY the chosen JSON.\n\n"
                + "\n\n".join(phase2_blocks)
            )

    user_prompt = (
        f"{handbook_block}"
        f"MEETING TRANSCRIPT SO FAR:\n{transcript_text}\n\n"
        f"{rules_text}\n\n"
        f"INSTRUCTION: {directed}\n\n"
        f"Respond with ONLY a valid JSON object matching one of the schemas above. "
        f"Do not include any text outside the JSON."
    )

    raw = await call_llm(full_system, user_prompt, model_temperature, model_max_tokens)
    if not raw:
        return MeetingTurnResponse(status="error", agent_id=agent_id, content_length=0)

    parsed = _parse_json_response(raw)
    if not parsed:
        parsed = {
            "message_type": req.expected_message_type or "COMMENT",
            "from_agent": agent_id,
            "points": [raw[:100]],
        }

    parsed = _unwrap_content_object(parsed)

    msg_type_hint = parsed.get("message_type") or req.expected_message_type or ""
    nested = _extract_nested_json_from_points(parsed, msg_type_hint)
    if nested:
        parsed = _unwrap_content_object(nested)

    parsed.setdefault("message_type", req.expected_message_type or "COMMENT")
    parsed.setdefault("from_agent", agent_id)
    parsed.setdefault("id", str(uuid.uuid4()))
    parsed.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
    parsed.setdefault("meeting_id", req.meeting_id)

    msg_type = parsed["message_type"]

    if req.phase == 2 and msg_type in ("PROPOSAL_REVISION", "PROPOSAL_SUBMISSION"):
        logger.info(f"Phase 2: converting {msg_type} to COMMENT for discussion")
        parsed = _summarize_proposal_for_discussion(parsed, agent_id, req.meeting_id)
        msg_type = "COMMENT"

    if not _validate_and_fill(parsed, msg_type):
        logger.warning(f"Message validation failed for {msg_type}, using raw fallback")
        parsed = {
            "message_type": "COMMENT",
            "from_agent": agent_id,
            "id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "meeting_id": req.meeting_id,
            "points": [raw[:2000]],
            "_original_expected_type": msg_type,
        }
        msg_type = "COMMENT"

    transcript_entry = {
        "from_agent": agent_id,
        "message_type": msg_type,
        "content": parsed,
        "timestamp": parsed["timestamp"],
    }
    await _append_to_transcript(req.context_ref, transcript_entry)

    content_str = json.dumps(parsed, indent=2)
    _write_history(req.phase, msg_type, content_str)
    logger.info(f"Published {msg_type} ({len(content_str)} chars)")

    return MeetingTurnResponse(
        status="success",
        agent_id=agent_id,
        message_type=msg_type,
        content=parsed,
        content_length=len(content_str),
    )


def _detect_repetition(transcript: list[dict], window: int = 8) -> str:
    """Analyze recent transcript for circular arguments. Returns a warning or empty string."""
    recent = transcript[-window:] if len(transcript) > window else transcript
    if len(recent) < 6:
        return ""
    themes: dict[str, int] = {}
    for entry in recent:
        content = entry.get("content", {})
        if isinstance(content, dict):
            desc = content.get("blocker_description", "") or content.get(
                "requirement", ""
            )
            if not desc:
                pts = content.get("points", [])
                desc = pts[0] if pts and isinstance(pts[0], str) else ""
        elif isinstance(content, str):
            desc = content
        else:
            desc = ""
        for keyword in desc.lower().split():
            if len(keyword) > 6:
                themes[keyword] = themes.get(keyword, 0) + 1
    repeated = [w for w, c in themes.items() if c >= 4]
    if len(repeated) >= 3:
        return (
            f"CONVERGENCE WARNING: The last {window} messages repeat the same themes "
            f"({', '.join(repeated[:5])}). The group is going in circles. "
            f"You should END_DISCUSSION or CLOSE_TOPIC to move forward."
        )
    return ""


@app.post("/facilitate", response_model=FacilitateResponse)
async def facilitate(req: FacilitateRequest):
    """Facilitator-only: read transcript and decide who speaks next."""
    logger.info("Facilitator decision requested")

    transcript = await _read_transcript(req.context_ref)
    transcript_text = _format_transcript_for_prompt(transcript)

    time_remaining = max(0, req.time_limit_seconds - req.elapsed_seconds)

    participant_list = (
        ", ".join(req.participant_ids) if req.participant_ids else "all participants"
    )
    author_note = ""
    if req.author_id:
        author_note = (
            f"\n\nNOTE: {req.author_id} is the PROPOSAL AUTHOR. "
            "They can respond to questions, clarify intent, and address concerns. "
            "Nominate them when reviewers raise questions the author should address."
        )

    convergence_warning = _detect_repetition(transcript)

    system = (
        "You are the Meeting Facilitator. Your job is to drive a rich, organic discussion.\n\n"
        "After reading the full transcript, decide what should happen next.\n\n"
        f"Available agents: {participant_list}"
        f"{author_note}\n\n"
        "Decision priority (use in this order):\n"
        "1. OPEN_FLOOR — your DEFAULT choice. Pose a topic or question and let agents "
        "self-select whether to respond. This creates the most natural discussion.\n"
        "2. NOMINATE — direct a specific question at 1-2 agents when you want a particular "
        "perspective (e.g., ask the author to respond to criticism, or ask the skeptic "
        "to challenge an assumption).\n"
        "3. PROMPT_SILENT — LAST RESORT only. Use this ONLY when specific agents have been "
        "silent for many turns and OPEN_FLOOR has not drawn them in. Do NOT use this as "
        "your first move.\n"
        "4. END_DISCUSSION — when the discussion has genuinely converged or time is running out.\n\n"
        "Rules:\n"
        "- Prefer OPEN_FLOOR and NOMINATE. Let agents decide for themselves if they have "
        "something to add. A good facilitator asks compelling questions, not forces people to talk.\n"
        "- When reviewers raise concerns, NOMINATE the author to respond.\n"
        "- Encourage follow-up questions, rebuttals, and deeper probing.\n"
        "- Rotate through participants. No agent can speak twice in a row.\n"
        "- Do NOT choose END_DISCUSSION until all agents have spoken at least once "
        "and at least 2 rounds of discussion have occurred.\n"
        "- If time remaining < 60 seconds, choose END_DISCUSSION.\n"
        "- If agents are repeating the same arguments, the discussion has converged. "
        "Use END_DISCUSSION rather than letting it loop.\n"
    )

    user_prompt = (
        f"TRANSCRIPT:\n{transcript_text}\n\n"
        f"MEETING STATE:\n"
        f"- Time remaining: {time_remaining:.0f}s / {req.time_limit_seconds:.0f}s\n"
        f"- Speaker turns so far: {len(req.speaker_history)}\n"
        f"- Recent speakers: {', '.join(req.speaker_history[-5:]) if req.speaker_history else 'none'}\n"
        f"- SILENT AGENTS (have NOT spoken yet): {', '.join(req.silent_agents) if req.silent_agents else 'ALL have spoken'}\n"
        f"- Proposal sections: {', '.join(req.proposal_sections) if req.proposal_sections else 'unknown'}\n"
        f"{f'⚠️ {convergence_warning}' if convergence_warning else ''}\n"
        f"{'⚠️ Some agents have not spoken yet. Try OPEN_FLOOR with a compelling question first. Only use PROMPT_SILENT if they remain silent after multiple OPEN_FLOOR attempts.' if req.silent_agents else ''}\n\n"
        f"Respond with ONLY a JSON object. Choose ONE decision:\n"
        f'{{"decision": "OPEN_FLOOR", "context": "topic or question for anyone to address"}} — PREFERRED: let agents self-select\n'
        f'{{"decision": "NOMINATE", "targets": ["agent-id", ...], "context": "directed question"}} — for specific perspectives\n'
        f'{{"decision": "PROMPT_SILENT", "targets": ["agent-id"], "context": "why they should speak"}} — LAST RESORT for persistently silent agents\n'
        f'{{"decision": "REFRAME", "message": "clarification to publish"}}\n'
        f'{{"decision": "CLOSE_TOPIC", "message": "topic being closed and why"}}\n'
        f'{{"decision": "END_DISCUSSION", "message": "reason to close discussion"}}\n'
    )

    raw = await call_llm(system, user_prompt, 0.3, 400)
    if not raw:
        return FacilitateResponse(
            status="fallback",
            decision="END_DISCUSSION",
            message="Facilitator LLM unavailable — forcing close",
        )

    parsed = _parse_json_response(raw)
    decision = parsed.get("decision", "END_DISCUSSION")

    if time_remaining < 60:
        decision = "END_DISCUSSION"
        parsed["message"] = "Time limit approaching — closing discussion."

    if decision == "REFRAME" or decision == "CLOSE_TOPIC":
        entry = {
            "from_agent": agent_id,
            "message_type": decision,
            "content": parsed.get("message", ""),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await _append_to_transcript(req.context_ref, entry)

    return FacilitateResponse(
        status="success",
        decision=decision,
        targets=parsed.get("targets", []),
        context=parsed.get("context", ""),
        message=parsed.get("message", ""),
    )


@app.post("/relevance_check", response_model=RelevanceCheckResponse)
async def relevance_check(req: RelevanceCheckRequest):
    """Evaluate whether a nomination is relevant and decide to speak or pass."""
    logger.info(f"Relevance check: {req.nomination_context[:80]}")

    transcript = await _read_transcript(req.context_ref)
    recent = transcript[-5:] if len(transcript) > 5 else transcript
    recent_text = _format_transcript_for_prompt(recent)

    system = (
        f"You are '{agent_id}'. {agent_soul}\n\n"
        f"The meeting facilitator has nominated you to respond.\n"
        f"You SHOULD accept unless you have literally nothing new to add.\n"
        f"In a technical spike meeting, every stakeholder perspective matters.\n"
        f"Default to ACCEPT. Only PASS if you have already spoken on this exact point."
    )
    user_prompt = (
        f"FACILITATOR'S CONTEXT: {req.nomination_context}\n\n"
        f"RECENT TRANSCRIPT:\n{recent_text}\n\n"
        f"You are being asked to contribute your domain perspective. "
        f"Accept unless you have already made this exact point.\n"
        f'Respond with ONLY: {{"decision": "ACCEPT", "reason": "..."}} '
        f'or {{"decision": "PASS", "reason": "..."}}'
    )

    raw = await call_llm(system, user_prompt, 0.2, 150)
    if not raw:
        return RelevanceCheckResponse(
            status="fallback", agent_id=agent_id, decision="PASS"
        )

    parsed = _parse_json_response(raw)
    decision = parsed.get("decision", "PASS").upper()
    if decision not in ("ACCEPT", "PASS"):
        decision = "ACCEPT" if "accept" in raw.lower() else "PASS"

    return RelevanceCheckResponse(
        status="success",
        agent_id=agent_id,
        decision=decision,
        reason=parsed.get("reason", ""),
    )


# ── Entry Point ───────────────────────────────────────────────────────────


def _load_prompts_for_agent(prompts_path: str, target_agent_id: str) -> dict:
    if not os.path.exists(prompts_path):
        return {}
    with open(prompts_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("agents", {}).get(target_agent_id, {})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Meeting sub-agent node")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--agent_id", type=str, required=True)
    parser.add_argument("--soul", type=str, required=True)
    parser.add_argument(
        "--model", type=str, default="gemini/gemini-2.5-flash-preview-04-17"
    )
    parser.add_argument("--output_dir", type=str, default="")
    parser.add_argument("--prompts_path", type=str, default="")
    parser.add_argument("--schemas_path", type=str, default="")
    parser.add_argument("--rules", type=str, default="[]")
    parser.add_argument("--skills", type=str, default="")
    args = parser.parse_args()

    if args.schemas_path:
        _load_schemas(args.schemas_path)

    agent_id = args.agent_id
    agent_soul = args.soul
    agent_model = args.model
    agent_skills = (
        [s.strip() for s in args.skills.split(",") if s.strip()] if args.skills else []
    )
    agent_output_dir = args.output_dir or os.path.join(
        os.path.dirname(__file__), "..", "agents", agent_id
    )

    try:
        meeting_rules = json.loads(args.rules)
    except (json.JSONDecodeError, TypeError):
        meeting_rules = []

    prompt_data = _load_prompts_for_agent(
        args.prompts_path
        or os.path.join(os.path.dirname(__file__), "agent_prompts.json"),
        agent_id,
    )
    base_system_prompt = prompt_data.get(
        "system_prompt", f"You are {agent_id}. {agent_soul}"
    )
    skills_text = ", ".join(agent_skills) if agent_skills else "General reasoning"
    system_prompt_text = f"{base_system_prompt}\nYour assigned skills: {skills_text}"
    model_config = prompt_data.get("model_config", {})
    model_temperature = model_config.get("temperature", 0.5)
    model_max_tokens = model_config.get("max_tokens", 800)

    os.makedirs(agent_output_dir, exist_ok=True)
    log_path = os.path.join(agent_output_dir, f"{agent_id}.log")
    logging.basicConfig(
        level=logging.INFO,
        format=f"%(asctime)s - [{agent_id}] - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    logger = logging.getLogger("meeting_node")
    logger.info(f"Starting {agent_id} | port={args.port} | model={agent_model}")

    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
