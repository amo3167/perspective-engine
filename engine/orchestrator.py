"""
Meeting Orchestrator — 5-Phase Facilitated Multi-Agent Meeting.

Spawns sub-agent processes (node.py), manages the facilitated
discussion loop, enforces time limits, and collects meeting output.

Phases:
    1. Proposal     — Author writes the initial document
    2. Discussion   — Facilitator-driven multi-turn conversation
    3. Synthesis    — Author incorporates feedback into revised proposal
    4. Governance   — Decision maker rules, Facilitator publishes meeting notes
    5. Final Review — Independent AI reviewer evaluates the entire meeting

Usage:
    python -m engine.orchestrator --topic "Should we adopt microservices?" \\
        --meeting-pack packs/technical-spike --output_dir ./output
"""

import sys
import os
import json
import asyncio
import logging
import time
import uuid
import re
from datetime import datetime
from pathlib import Path

import litellm

litellm.drop_params = True

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from engine.shared_memory import SharedMemory
from engine.pack_loader import load_pack
from engine.agent_processes import kill_old_nodes, start_nodes, cleanup_nodes
from engine.runtime import ssl_verify_enabled
from engine.http_client import (
    notify_backend,
    trigger_meeting_turn,
    trigger_facilitate,
    trigger_relevance_check,
)

litellm.ssl_verify = ssl_verify_enabled()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("meeting_orchestrator")

TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")


# ── Meeting Phases ────────────────────────────────────────────────────────


async def run_phase_1(
    author_port: int,
    context_ref: str,
    meeting_id: str,
    topic: str,
    author_id: str = "author",
    proposal_sections: list[str] | None = None,
    phase_config: dict | None = None,
) -> bool:
    pc = phase_config or {}
    phase_label = pc.get("label", "Proposal")
    expected_type = pc.get("expected_type", "PROPOSAL_SUBMISSION")
    logger.info(f"=== PHASE 1: {phase_label.upper()} ===")

    sections_csv = ", ".join(
        proposal_sections
        or [
            "problem_statement",
            "proposed_solution",
            "impact_areas",
            "rollback_strategy",
            "timeline",
        ]
    )
    template_prompt = pc.get("prompt", "")
    if template_prompt:
        prompt = template_prompt.replace("${topic}", topic).replace(
            "${proposal_sections_csv}", sections_csv
        )
    else:
        prompt = (
            f"Write the initial spike document for this topic:\n\n"
            f"TOPIC: {topic}\n\n"
            f"Use the read_reference_file tool to read relevant reference documents "
            f"listed in the handbook before drafting your proposal.\n\n"
            f"Submit a {expected_type} with a spike_document containing: "
            f"title, {sections_csv}."
        )

    result = await trigger_meeting_turn(
        author_port,
        context_ref,
        meeting_id,
        phase=1,
        directed_prompt=prompt,
        expected_message_type=expected_type,
    )

    actual_type = result.get("message_type", "")
    if result.get("status") != "success":
        logger.error("Phase 1 failed: author could not produce proposal")
        return False

    if actual_type != expected_type:
        logger.warning(
            f"Phase 1: expected {expected_type} but got {actual_type} — retrying once"
        )
        result = await trigger_meeting_turn(
            author_port,
            context_ref,
            meeting_id,
            phase=1,
            directed_prompt=f"Your previous response was not a {expected_type}. "
            f"You MUST respond with exactly a {expected_type} JSON object.\n\n{prompt}",
            expected_message_type=expected_type,
        )
        if (
            result.get("status") != "success"
            or result.get("message_type") != expected_type
        ):
            logger.error(
                f"Phase 1 retry failed: got {result.get('message_type')} instead of {expected_type}"
            )
            return False

    await notify_backend(
        {
            "meeting_type": "meeting_turn",
            "from_agent": author_id,
            "message_type": result.get("message_type", "PROPOSAL_SUBMISSION"),
            "content": result.get("content", ""),
            "phase": 1,
            "meeting_id": meeting_id,
            "timestamp": datetime.now().isoformat(),
        }
    )

    await notify_backend(
        {
            "meeting_type": "phase_complete",
            "phase": 1,
            "meeting_id": meeting_id,
            "timestamp": datetime.now().isoformat(),
        }
    )
    logger.info("Phase 1 complete: proposal submitted")
    return True


async def run_phase_2(
    facilitator_port: int,
    reviewer_ports: dict[str, int],
    context_ref: str,
    meeting_id: str,
    time_limit: float,
    proposal_sections: list[str],
    author_port: int | None = None,
    author_id: str = "",
    facilitator_id: str = "facilitator",
    phase_config: dict | None = None,
) -> None:
    pc = phase_config or {}
    phase_label = pc.get("label", "Facilitated Discussion")
    max_turns = pc.get("max_turns", 20)
    logger.info(f"=== PHASE 2: {phase_label.upper()} (max {max_turns} turns) ===")
    start_time = time.time()
    speaker_history: list[str] = []
    participant_ports = dict(reviewer_ports)
    if author_port and author_id:
        participant_ports[author_id] = author_port
    all_reviewer_ids = list(participant_ports.keys())
    consecutive_rejections = 0
    silent_override_count = 0
    logger.info(f"  Participants: {all_reviewer_ids}")

    for turn in range(max_turns):
        elapsed = time.time() - start_time
        if elapsed >= time_limit:
            logger.warning(f"Time limit reached ({elapsed:.0f}s / {time_limit:.0f}s)")
            break

        if len(speaker_history) >= max_turns:
            logger.info(f"Hard turn limit reached ({max_turns} speaker turns)")
            break

        spoken_set = set(speaker_history)
        silent = [a for a in all_reviewer_ids if a not in spoken_set]

        fac_result = await trigger_facilitate(
            facilitator_port,
            context_ref,
            meeting_id,
            elapsed,
            time_limit,
            speaker_history,
            silent,
            proposal_sections,
            participant_ids=all_reviewer_ids,
            author_id=author_id,
        )

        decision = fac_result.get("decision", "END_DISCUSSION")
        targets = fac_result.get("targets", [])
        context = fac_result.get("context", "")
        logger.info(
            f"Turn {turn + 1}: facilitator says {decision} -> {targets or context[:50]}"
        )

        if decision == "END_DISCUSSION":
            if silent:
                silent_override_count += 1
                if silent_override_count <= 2:
                    logger.warning(
                        f"Overriding END_DISCUSSION → OPEN_FLOOR "
                        f"({len(silent)} silent, attempt {silent_override_count}/2)"
                    )
                    decision = "OPEN_FLOOR"
                    context = "We haven't heard from everyone yet. What are your thoughts on the proposal so far?"
                else:
                    logger.warning(
                        f"Overriding END_DISCUSSION → PROMPT_SILENT "
                        f"({len(silent)} still silent after {silent_override_count} attempts)"
                    )
                    decision = "PROMPT_SILENT"
                    targets = silent[:2]
                    context = "You haven't spoken yet. Please share your perspective."
            else:
                logger.info("Facilitator ended discussion")
                break

        if decision == "REFRAME" or decision == "CLOSE_TOPIC":
            speaker_history.append(facilitator_id)
            await notify_backend(
                {
                    "meeting_type": "facilitator_decision",
                    "decision": decision,
                    "context": fac_result.get("message", ""),
                    "targets": targets,
                    "meeting_id": meeting_id,
                    "timestamp": datetime.now().isoformat(),
                }
            )
            continue

        agents_to_trigger: list[str] = []

        if decision == "PROMPT_SILENT":
            agents_to_trigger = [t for t in targets if t in participant_ports]

        elif decision in ("NOMINATE", "OPEN_FLOOR"):
            check_targets = targets if decision == "NOMINATE" else all_reviewer_ids

            last_speaker = speaker_history[-1] if speaker_history else None
            check_targets = [
                a for a in check_targets if a in participant_ports and a != last_speaker
            ]

            checks = await asyncio.gather(
                *[
                    trigger_relevance_check(
                        participant_ports[a],
                        context_ref,
                        meeting_id,
                        context,
                    )
                    for a in check_targets
                ]
            )
            for agent_id_check, check_result in zip(check_targets, checks):
                if check_result.get("decision") == "ACCEPT":
                    agents_to_trigger.append(agent_id_check)

        if not agents_to_trigger:
            consecutive_rejections += 1
            if consecutive_rejections >= 4 and silent:
                forced = silent[0]
                logger.info(
                    f"Forcing silent agent {forced} after "
                    f"{consecutive_rejections} consecutive rejections"
                )
                agents_to_trigger = [forced]
                consecutive_rejections = 0
            else:
                logger.info(
                    f"No agents accepted ({consecutive_rejections}/4 rejections), "
                    "continuing..."
                )
                continue

        for target_id in agents_to_trigger:
            last_speaker = speaker_history[-1] if speaker_history else None
            if target_id == last_speaker:
                continue

            is_author = target_id == author_id
            phase2_prompt = context
            if is_author:
                phase2_prompt = (
                    f"{context}\n\n"
                    "You are the PROPOSAL AUTHOR participating in the discussion phase. "
                    "Do NOT produce a PROPOSAL_REVISION — that comes later in Phase 3.\n"
                    "Instead, respond to the feedback with one of:\n"
                    "- COMMENT: acknowledge points, clarify intent, answer questions\n"
                    "- AGREE: accept a specific change request\n"
                    "- DISAGREE: push back on a specific point with justification\n"
                    "Keep your response focused on the specific feedback being discussed."
                )

            turn_result = await trigger_meeting_turn(
                participant_ports[target_id],
                context_ref,
                meeting_id,
                phase=2,
                directed_prompt=phase2_prompt,
            )

            if turn_result.get("status") == "success":
                speaker_history.append(target_id)
                consecutive_rejections = 0
                msg_type = turn_result.get("message_type", "COMMENT")
                await notify_backend(
                    {
                        "meeting_type": "meeting_turn",
                        "from_agent": target_id,
                        "message_type": msg_type,
                        "content": turn_result.get("content", ""),
                        "phase": 2,
                        "meeting_id": meeting_id,
                        "timestamp": datetime.now().isoformat(),
                    }
                )

            await asyncio.sleep(1)

    await notify_backend(
        {
            "meeting_type": "phase_complete",
            "phase": 2,
            "meeting_id": meeting_id,
            "turns": len(speaker_history),
            "timestamp": datetime.now().isoformat(),
        }
    )
    logger.info(f"Phase 2 complete: {len(speaker_history)} turns")


async def run_phase_3(
    author_port: int,
    context_ref: str,
    meeting_id: str,
    author_id: str = "author",
) -> bool:
    logger.info("=== PHASE 3: SYNTHESIS ===")

    prompt = (
        "The discussion phase is complete. You now have all reviewer feedback.\n\n"
        "Read the full transcript and produce a PROPOSAL_REVISION that:\n"
        "1. Incorporates non-blocking suggestions\n"
        "2. Acknowledges agreements\n"
        "3. Offers explicit compromises for disagreements\n"
        "4. Flags any unresolved blockers for the Architect\n\n"
        "Include updated_spike_document and feedback_addressed sections."
    )

    result = await trigger_meeting_turn(
        author_port,
        context_ref,
        meeting_id,
        phase=3,
        directed_prompt=prompt,
        expected_message_type="PROPOSAL_REVISION",
    )

    success = result.get("status") == "success"
    if success:
        logger.info("Phase 3 complete: proposal revised")
        await notify_backend(
            {
                "meeting_type": "meeting_turn",
                "from_agent": author_id,
                "message_type": result.get("message_type", "PROPOSAL_REVISION"),
                "content": result.get("content", ""),
                "phase": 3,
                "meeting_id": meeting_id,
                "timestamp": datetime.now().isoformat(),
            }
        )
    else:
        logger.error("Phase 3 failed: author could not synthesize")

    await notify_backend(
        {
            "meeting_type": "phase_complete",
            "phase": 3,
            "meeting_id": meeting_id,
            "timestamp": datetime.now().isoformat(),
        }
    )
    return success


async def run_phase_4(
    architect_port: int,
    facilitator_port: int,
    context_ref: str,
    meeting_id: str,
    architect_id: str = "architect",
    facilitator_id: str = "facilitator",
    phase_config: dict | None = None,
) -> dict:
    pc = phase_config or {}
    phase_label = pc.get("label", "Governance")
    decision_type = pc.get("expected_type", "ARCHITECT_APPROVAL")
    decision_prompt = pc.get(
        "prompt",
        (
            "The author has submitted a revised proposal incorporating all feedback.\n"
            f"Read the full transcript and issue your {decision_type}.\n"
            "Decision must be APPROVED, CONDITIONAL, or REJECTED.\n"
            "Include rationale and conditions (if CONDITIONAL)."
        ),
    )
    follow_up = pc.get("follow_up", {})
    notes_type = follow_up.get("expected_type", "MEETING_NOTES")
    notes_prompt = follow_up.get(
        "prompt",
        (
            "The meeting is now complete. Read the full transcript and produce MEETING_NOTES.\n"
            "Include: executive_summary, key_objections, accepted_compromises, "
            "decisions, and audit_trail."
        ),
    )

    logger.info(f"=== PHASE 4: {phase_label.upper()} ===")

    arch_result = await trigger_meeting_turn(
        architect_port,
        context_ref,
        meeting_id,
        phase=4,
        directed_prompt=decision_prompt,
        expected_message_type=decision_type,
    )

    architect_decision = "UNKNOWN"
    if arch_result.get("status") == "success":
        content = arch_result.get("content", {})
        architect_decision = content.get("decision", "UNKNOWN")
        logger.info(f"Architect decision: {architect_decision}")
        await notify_backend(
            {
                "meeting_type": "meeting_turn",
                "from_agent": architect_id,
                "message_type": arch_result.get("message_type", decision_type),
                "content": content,
                "phase": 4,
                "meeting_id": meeting_id,
                "timestamp": datetime.now().isoformat(),
            }
        )

    notes_result = await trigger_meeting_turn(
        facilitator_port,
        context_ref,
        meeting_id,
        phase=4,
        directed_prompt=notes_prompt,
        expected_message_type=notes_type,
    )

    if notes_result.get("status") == "success":
        await notify_backend(
            {
                "meeting_type": "meeting_turn",
                "from_agent": facilitator_id,
                "message_type": notes_result.get("message_type", "MEETING_NOTES"),
                "content": notes_result.get("content", ""),
                "phase": 4,
                "meeting_id": meeting_id,
                "timestamp": datetime.now().isoformat(),
            }
        )

    await notify_backend(
        {
            "meeting_type": "phase_complete",
            "phase": 4,
            "meeting_id": meeting_id,
            "architect_decision": architect_decision,
            "timestamp": datetime.now().isoformat(),
        }
    )

    logger.info("Phase 4 complete: governance done")
    return {
        "architect_decision": architect_decision,
        "architect_content": arch_result.get("content"),
        "meeting_notes": notes_result.get("content"),
    }


FINAL_REVIEW_SYSTEM_PROMPT = """\
You are an independent senior reviewer conducting a post-meeting quality assessment.
You did NOT participate in the meeting. You are reading the full transcript and final
decision for the first time, with fresh eyes.

## What You Evaluate

1. **Decision quality** — Is the final decision sound? Are conditions proportionate to
   the actual risk, or over/under-engineered? Would you sign off on this?
   Do NOT accept the group's framing at face value. Challenge the metaphors, labels,
   and mental models the group chose. If their framing has risks they didn't see, say so.
2. **Meeting process quality** — Be QUANTITATIVE. Count turns per agent and report
   ratios (e.g., "agent-X spoke in 5 of 16 discussion turns — 31%"). Flag agents who
   were underutilized or dominant using these numbers, not vague language.
   Evaluate: facilitator effectiveness, echo chamber effects, negativity spirals,
   whether viewpoints got genuinely diverse coverage.
3. **Strengths** — What the group got right. Be specific: cite agent names and turns.
4. **Blind spots** — What was missed entirely. Unconsidered scenarios, edge cases,
   logical gaps the group never explored.
5. **Evidence quality** — Were cited examples and statistics plausible? Flag anything
   that looks fabricated, unverified, or misapplied. This is CRITICAL — agents will
   invent statistics and cite non-existent studies. Call out every one you find.
6. **Meta-observations** — Look for recursive or self-referential patterns. If the
   meeting topic relates to the meeting process itself, flag it. If the meeting's own
   dynamics are evidence for or against the decision, say so explicitly.
7. **Recommendations** — Maximum 4 recommendations. Consolidate related items into
   single recommendations with sub-actions. Each must have clear timing
   (pre/during/post-execution). Fewer, sharper recommendations beat a long list.
8. **Confidence score with gap analysis** — Rate 1-10 AND explain what specific
   actions would raise the score by 1-2 points.

## Your Style

Be DIRECT and OPINIONATED. You are the last line of defense before this decision gets
executed. Your value is inversely proportional to how diplomatic you are.

Rules:
- NEVER contradict yourself. If you say "the decision is sound" then immediately flag
  a major gap, resolve to the stronger position. Either it's sound or it's incomplete.
- If the group got something fundamentally wrong, say so in the overall_assessment.
- If a condition is theater (looks good but achieves nothing), call it out by name.
- If the decision is too cautious, say "this is too cautious because X."
- If evidence was fabricated, lead with it — don't bury it in a list.
- Challenge the group's chosen language. If their metaphor or framing creates risks
  they didn't discuss, that's a blind spot.

Cite turn numbers and agent names when referencing the transcript.

Respond with a JSON object matching the FINAL_REVIEW schema exactly.
"""


async def run_phase_5(
    context_ref: str,
    meeting_id: str,
    governance: dict,
    model: str,
    review_schema: dict | None = None,
    phase_config: dict | None = None,
) -> dict:
    """Phase 5: Independent final review via direct LLM call (no agent node)."""
    pc = phase_config or {}
    phase_label = pc.get("label", "Final Review")
    logger.info(f"=== PHASE 5: {phase_label.upper()} ===")

    mem_local = SharedMemory()
    data = await mem_local.get_context_ref(context_ref)
    transcript = data.get("transcript", []) if data else []

    transcript_text = json.dumps(transcript, indent=2, default=str)

    decision = governance.get("architect_decision", "UNKNOWN")
    arch_content = governance.get("architect_content", {}) or {}
    decision_summary = json.dumps(arch_content, indent=2, default=str)

    schema_hint = ""
    if review_schema:
        schema_hint = (
            "\n\nYou MUST respond with a JSON object matching this schema exactly:\n"
            f"```json\n{json.dumps(review_schema, indent=2)}\n```"
        )

    user_prompt = (
        f"## Meeting Transcript ({len(transcript)} turns)\n\n"
        f"{transcript_text}\n\n"
        f"## Final Decision: {decision}\n\n"
        f"{decision_summary}\n\n"
        f"## Your Task\n\n"
        f"Review the entire meeting and final decision. Provide your independent "
        f"assessment as a FINAL_REVIEW."
        f"{schema_hint}"
    )

    try:
        resp = await litellm.acompletion(
            model=model,
            messages=[
                {"role": "system", "content": FINAL_REVIEW_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=4096,
            temperature=0.3,
        )
        raw = resp.choices[0].message.content or ""

        content = {}
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        try:
            content = json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r"\{[\s\S]*\}", cleaned)
            if match:
                try:
                    content = json.loads(match.group(0))
                except json.JSONDecodeError:
                    pass
            if not content:
                content = {"raw_review": raw, "message_type": "FINAL_REVIEW"}

        if "message_type" not in content:
            content["message_type"] = "FINAL_REVIEW"

        logger.info(f"Phase 5 complete: review generated ({len(raw)} chars)")

        await notify_backend(
            {
                "meeting_type": "meeting_turn",
                "from_agent": "final-reviewer",
                "message_type": "FINAL_REVIEW",
                "content": content,
                "phase": 5,
                "meeting_id": meeting_id,
                "timestamp": datetime.now().isoformat(),
            }
        )

        await notify_backend(
            {
                "meeting_type": "phase_complete",
                "phase": 5,
                "meeting_id": meeting_id,
                "timestamp": datetime.now().isoformat(),
            }
        )

        return content

    except Exception as e:
        logger.error(f"Phase 5 failed: {e}")
        return {"error": str(e), "message_type": "FINAL_REVIEW"}


# ── Transcript Monitor ────────────────────────────────────────────────────


async def monitor_transcript(
    context_ref: str, stop_event: asyncio.Event, meeting_id: str = ""
):
    mem_local = SharedMemory()
    last_count = 0
    while not stop_event.is_set():
        try:
            data = await mem_local.get_context_ref(context_ref)
            if data:
                transcript = data.get("transcript", [])
                if len(transcript) > last_count:
                    for entry in transcript[last_count:]:
                        speaker = entry.get("from_agent", "system")
                        msg_type = entry.get("message_type", "")
                        content = entry.get("content", "")
                        if isinstance(content, dict):
                            display = json.dumps(content, indent=2)[:300]
                        else:
                            display = str(content)[:300]
                        print(f"\n[{speaker}] ({msg_type}):\n{display}")
                    last_count = len(transcript)
        except Exception:
            pass
        await asyncio.sleep(2)


# ── Output Writer ────────────────────────────────────────────────────────

_RESERVED_SCHEMA_KEYS = frozenset(
    {
        "message_type",
        "feedback_addressed",
        "from_agent",
        "id",
        "timestamp",
        "meeting_id",
    }
)


def _extract_nested_field(data: dict, field: str) -> str:
    for key, val in data.items():
        if isinstance(val, dict) and field in val:
            return val[field]
        if isinstance(val, list):
            for item in val:
                if isinstance(item, str) and field in item:
                    try:
                        parsed = (
                            json.loads(item) if item.strip().startswith("{") else None
                        )
                        if parsed and field in parsed:
                            return parsed[field]
                    except (json.JSONDecodeError, TypeError):
                        pass
    return ""


def _discover_proposal_key(schemas: dict, message_type: str) -> str | None:
    schema = schemas.get(message_type, {})
    for key in schema:
        if key not in _RESERVED_SCHEMA_KEYS:
            val = schema[key]
            if isinstance(val, dict) and len(val) > 1:
                return key
    return None


def _try_extract_proposal_doc(
    content: dict,
    proposal_keys: list[str] | None = None,
) -> dict:
    if not proposal_keys:
        proposal_keys = ["updated_spike_document", "spike_document"]
    for key in ("points", "raw"):
        items = content.get(key, [])
        if isinstance(items, str):
            items = [items]
        for item in items:
            if not isinstance(item, str):
                continue
            text = item.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            try:
                parsed = json.loads(text) if text.startswith("{") else None
                if parsed:
                    for pk in proposal_keys:
                        doc = parsed.get(pk)
                        if doc and isinstance(doc, dict) and len(doc) > 1:
                            return doc
            except (json.JSONDecodeError, TypeError):
                pass
    return content


def _render_item(item) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        desc = item.get("description") or item.get("action") or item.get("text") or ""
        parts = [desc] if desc else []
        for k in ("agents", "owner", "priority", "timing", "rationale", "concern"):
            v = item.get(k)
            if v:
                label = k.replace("_", " ").title()
                parts.append(
                    f"  *{label}: {v if isinstance(v, str) else ', '.join(v)}*"
                )
        sub_lists = item.get("missed_questions") or []
        for q in sub_lists:
            parts.append(f"  - {q}")
        return "\n".join(parts) if parts else json.dumps(item, default=str)
    return str(item)


async def write_outputs(
    context_ref: str,
    output_dir: str,
    meeting_id: str,
    governance: dict,
    start_time: float,
    proposal_sections: list[str] | None = None,
    schemas: dict | None = None,
    template_name: str = "meeting",
    review_content: dict | None = None,
):
    mem_local = SharedMemory()
    data = await mem_local.get_context_ref(context_ref)
    transcript = data.get("transcript", []) if data else []
    # Offload the blocking file writes to a worker thread so they never stall
    # the event loop (and never issue synchronous open() inside a coroutine).
    await asyncio.to_thread(
        _write_outputs_sync,
        output_dir,
        transcript,
        meeting_id,
        governance,
        start_time,
        proposal_sections,
        schemas,
        template_name,
        review_content,
    )


def _write_outputs_sync(
    output_dir: str,
    transcript: list,
    meeting_id: str,
    governance: dict,
    start_time: float,
    proposal_sections: list[str] | None,
    schemas: dict | None,
    template_name: str,
    review_content: dict | None,
) -> None:
    os.makedirs(output_dir, exist_ok=True)

    with open(
        os.path.join(output_dir, "meeting_transcript.json"), "w", encoding="utf-8"
    ) as f:
        json.dump(transcript, f, indent=2, default=str)

    notes = governance.get("meeting_notes")
    notes_md = ""
    if notes:
        if isinstance(notes, dict):
            notes_md = notes.get("executive_summary", "")
            if not notes_md:
                notes_md = _extract_nested_field(notes, "executive_summary")
        else:
            notes_md = str(notes)
    # The LLM may return executive_summary as a list of bullets or a nested
    # object; coerce to a string so the markdown concatenation below can't raise.
    if isinstance(notes_md, list):
        notes_md = "\n".join(f"- {x}" for x in notes_md)
    elif not isinstance(notes_md, str):
        notes_md = str(notes_md) if notes_md else ""
    arch_content = governance.get("architect_content", {}) or {}
    with open(os.path.join(output_dir, "meeting_notes.md"), "w", encoding="utf-8") as f:
        f.write(f"# Meeting Notes — {meeting_id}\n\n")
        f.write(f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")
        f.write(
            f"**Architect Decision:** {governance.get('architect_decision', 'UNKNOWN')}\n\n"
        )
        f.write("## Executive Summary\n\n")
        f.write((notes_md or "Meeting notes not available.") + "\n\n")
        rationale = arch_content.get("rationale", [])
        if rationale:
            f.write("## Architect Rationale\n\n")
            for r in rationale if isinstance(rationale, list) else [rationale]:
                f.write(f"- {r}\n")
            f.write("\n")
        conditions = arch_content.get("conditions", [])
        if conditions:
            f.write("## Conditions\n\n")
            for c in conditions:
                if isinstance(c, dict):
                    label = c.get("requirement", "") or c.get("id", "")
                    details = c.get("details", "") or c.get("description", "")
                    owner = c.get("owner", "TBD")
                    due = c.get("due_date", "TBD")
                    line = f"- **{label}** (owner: {owner}, due: {due})"
                    if details:
                        line += f": {details}"
                    f.write(line + "\n")
                else:
                    f.write(f"- {c}\n")
            f.write("\n")

    revision_entries = [
        e for e in transcript if e.get("message_type") == "PROPOSAL_REVISION"
    ]
    if not revision_entries:
        revision_entries = [
            e
            for e in transcript
            if isinstance(e.get("content"), dict)
            and e["content"].get("_original_expected_type") == "PROPOSAL_REVISION"
        ]
    if revision_entries:
        schemas = schemas or {}
        sections = proposal_sections or [
            "problem_statement",
            "proposed_solution",
            "impact_areas",
            "rollback_strategy",
            "timeline",
        ]

        revision_key = _discover_proposal_key(schemas, "PROPOSAL_REVISION")
        submission_key = _discover_proposal_key(schemas, "PROPOSAL_SUBMISSION")
        lookup_keys = [k for k in (revision_key, submission_key) if k]
        if not lookup_keys:
            lookup_keys = ["updated_spike_document", "spike_document"]

        final = revision_entries[-1].get("content", {})
        doc = None
        for k in lookup_keys:
            doc = final.get(k)
            if doc and isinstance(doc, dict):
                break
        if not doc or not isinstance(doc, dict):
            doc = _try_extract_proposal_doc(final, proposal_keys=lookup_keys)

        heading_label = template_name.replace("_", " ").title()
        with open(
            os.path.join(output_dir, "proposal_final.md"), "w", encoding="utf-8"
        ) as f:
            f.write(f"# {doc.get('title', heading_label + ' — Proposal')}\n\n")
            for section in sections:
                val = doc.get(section, "")
                section_heading = section.replace("_", " ").title()
                f.write(f"## {section_heading}\n\n")
                if isinstance(val, dict):
                    for sub_key, sub_val in val.items():
                        sub_heading = sub_key.replace("_", " ").title()
                        f.write(f"### {sub_heading}\n\n")
                        if isinstance(sub_val, list):
                            for item in sub_val:
                                f.write(f"- {item}\n")
                        else:
                            f.write(f"{sub_val}\n")
                        f.write("\n")
                elif isinstance(val, list):
                    for item in val:
                        f.write(f"- {item}\n")
                    f.write("\n")
                else:
                    f.write(f"{val}\n\n")

    if review_content and not review_content.get("error"):
        _write_final_review(output_dir, meeting_id, review_content)

    elapsed = time.time() - start_time
    meta = {
        "meeting_id": meeting_id,
        "timestamp": datetime.now().isoformat(),
        "elapsed_seconds": round(elapsed, 1),
        "total_turns": len(transcript),
        "architect_decision": governance.get("architect_decision"),
        "has_final_review": bool(review_content and not review_content.get("error")),
    }
    with open(
        os.path.join(output_dir, "pipeline_meta.json"), "w", encoding="utf-8"
    ) as f:
        json.dump(meta, f, indent=2)

    logger.info(f"Outputs written to {output_dir}")


def _write_final_review(output_dir: str, meeting_id: str, review_content: dict) -> None:
    review_md_path = os.path.join(output_dir, "final_review.md")
    with open(review_md_path, "w", encoding="utf-8") as f:
        f.write(f"# Final Review — {meeting_id}\n\n")
        f.write(f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n")

        for section_key, heading in [
            ("overall_assessment", "Overall Assessment"),
            ("decision_quality", "Decision Quality"),
        ]:
            val = review_content.get(section_key, "")
            if val:
                text = (
                    val
                    if isinstance(val, str)
                    else json.dumps(val, indent=2, default=str)
                )
                f.write(f"## {heading}\n\n{text}\n\n")

        process = review_content.get("process_quality")
        if process and isinstance(process, dict):
            f.write("## Process Quality\n\n")
            for pk, plabel in [
                ("facilitator_effectiveness", "Facilitator Effectiveness"),
                ("agent_utilization", "Agent Utilization"),
                ("discussion_balance", "Discussion Balance"),
            ]:
                pv = process.get(pk, "")
                if not pv:
                    continue
                if isinstance(pv, str):
                    f.write(f"**{plabel}:** {pv}\n\n")
                elif isinstance(pv, dict):
                    f.write(f"**{plabel}:**\n\n")
                    for dk, dv in pv.items():
                        label = dk.replace("_", " ").title()
                        if isinstance(dv, dict):
                            items = [f"{k}: {v}" for k, v in dv.items()]
                            f.write(f"- *{label}:* {', '.join(items)}\n")
                        elif isinstance(dv, list):
                            f.write(f"- *{label}:* {', '.join(str(x) for x in dv)}\n")
                        else:
                            f.write(f"- *{label}:* {dv}\n")
                    f.write("\n")
                else:
                    f.write(f"**{plabel}:** {pv}\n\n")

        meta = review_content.get("meta_observations", "")
        if meta:
            text = meta if isinstance(meta, str) else json.dumps(meta, default=str)
            f.write(f"## Meta-Observations\n\n{text}\n\n")

        for section_key, heading in [
            ("strengths", "Strengths"),
            ("blind_spots", "Blind Spots"),
            ("recommendations", "Recommendations"),
        ]:
            items = review_content.get(section_key, [])
            if items:
                f.write(f"## {heading}\n\n")
                if isinstance(items, list):
                    for item in items:
                        f.write(f"- {_render_item(item)}\n")
                else:
                    f.write(f"{items}\n")
                f.write("\n")

        evidence = review_content.get("evidence_quality", "")
        if evidence:
            _write_evidence_section(f, evidence)

        confidence = review_content.get("confidence_score")
        if confidence is not None:
            f.write(f"## Confidence Score\n\n**{confidence}/10**\n\n")

        gap = review_content.get("confidence_gap", "")
        if gap:
            text = gap if isinstance(gap, str) else json.dumps(gap, default=str)
            f.write(f"### What Would Raise It\n\n{text}\n\n")

        raw = review_content.get("raw_review", "")
        if raw and not review_content.get("strengths"):
            f.write(f"## Raw Review\n\n{raw}\n\n")

    logger.info(f"Final review written to {review_md_path}")


def _write_evidence_section(f, evidence) -> None:
    f.write("## Evidence Quality\n\n")
    if isinstance(evidence, str):
        f.write(f"{evidence}\n\n")
        return
    if isinstance(evidence, list):
        for e in evidence:
            f.write(f"- {_render_item(e)}\n")
        f.write("\n")
        return
    if not isinstance(evidence, dict):
        f.write(f"{evidence}\n\n")
        return

    def _render_evidence_list(items: list) -> None:
        for e in items:
            if isinstance(e, dict):
                claim = e.get("claim") or e.get("evidence") or e.get("text") or ""
                agent = e.get("agent", "")
                turn = e.get("turn")
                concern = e.get("concern") or e.get("usage") or e.get("verdict") or ""
                citation = (
                    f" *({agent}, turn {turn})*"
                    if agent and turn
                    else (f" *({agent})*" if agent else "")
                )
                f.write(f"- {claim}{citation}")
                if concern:
                    f.write(f"\n  *{concern}*")
                f.write("\n")
            else:
                f.write(f"- {e}\n")

    wrote = False
    for sub_key, sub_label in [
        ("fabricated_or_suspicious", "Fabricated or Suspicious"),
        ("suspicious_or_misused", "Flagged Evidence"),
        ("fabricated_claims", "Fabricated Claims"),
        ("unverified_statistics", "Unverified Statistics"),
    ]:
        sub_items = evidence.get(sub_key, [])
        if sub_items:
            wrote = True
            f.write(f"### {sub_label}\n\n")
            _render_evidence_list(
                sub_items if isinstance(sub_items, list) else [sub_items]
            )
            f.write("\n")

    for sub_key, sub_label in [
        ("well_used", "Well-Used Evidence"),
        ("plausible_and_well_used", "Well-Used Evidence"),
        ("plausible_evidence", "Plausible Evidence"),
    ]:
        sub_items = evidence.get(sub_key, [])
        if sub_items:
            wrote = True
            f.write(f"### {sub_label}\n\n")
            _render_evidence_list(
                sub_items if isinstance(sub_items, list) else [sub_items]
            )
            f.write("\n")

    if not wrote:
        for k, v in evidence.items():
            label = k.replace("_", " ").title()
            f.write(f"### {label}\n\n")
            if isinstance(v, list):
                _render_evidence_list(v)
            elif isinstance(v, str):
                f.write(f"{v}\n")
            else:
                f.write(f"{json.dumps(v, indent=2, default=str)}\n")
            f.write("\n")


# ── Main Orchestration ────────────────────────────────────────────────────

mem = SharedMemory()


def _resolve_architect_port(
    port_map: dict[str, int],
    architect_id: str | None,
    reviewers: list[dict],
) -> tuple[int | None, str | None]:
    """Resolve the port that runs Phase-4 governance.

    Prefer the explicit architect; otherwise fall back to the first reviewer.
    Returns ``(None, None)`` when neither is available so the caller can skip
    governance instead of crashing on ``reviewers[0]`` for a pack that resolves
    zero reviewers.
    """
    if architect_id and architect_id in port_map:
        return port_map[architect_id], architect_id
    if reviewers:
        rid = reviewers[0].get("id")
        if rid in port_map:
            return port_map[rid], rid
    return None, None


async def run_meeting(
    topic: str,
    domain_handbook: str = "",
    context_dir: str = "",
    output_dir: str = "",
    pack_dir: str = "",
):
    meeting_id = str(uuid.uuid4())
    start_time = time.time()

    pack = load_pack(pack_dir=pack_dir, context_path="")

    if domain_handbook:
        pack.domain_handbook = domain_handbook
    if context_dir:
        pack.context_dir = context_dir

    agent_by_id, facilitator, author, architect_id, reviewers = pack.resolve_roles()

    if not facilitator or not author:
        logger.error(
            "Missing facilitator or author — check meeting_template.json roles and profiles.json"
        )
        return

    if not output_dir:
        output_dir = str(Path(PROJECT_ROOT) / "output" / f"meeting_{TIMESTAMP}")

    run_dir = str(Path(PROJECT_ROOT) / ".runs" / f"run_{TIMESTAMP}")

    kill_old_nodes()

    processes = await start_nodes(
        pack.agents,
        run_dir,
        pack.model_map,
        pack.rules_tips,
        prompts_path=pack.prompts_path,
        schemas_path=pack.schemas_path,
    )

    port_map = {a["id"]: a["port"] for a in pack.agents}

    discussion_phase = pack.phase_by_id("discussion") or {}
    phase2_participants = discussion_phase.get("participants", ["reviewers"])

    reviewer_ports: dict[str, int] = {}
    for role_ref in phase2_participants:
        agent_ids = pack.roles.get(role_ref, [])
        if isinstance(agent_ids, str):
            agent_ids = [agent_ids]
        for aid in agent_ids:
            if aid in port_map:
                reviewer_ports[aid] = port_map[aid]
    if not reviewer_ports:
        reviewer_ports = {a["id"]: a["port"] for a in reviewers}

    debate_data = {
        "topic": topic,
        "meeting_id": meeting_id,
        "domain_handbook": pack.domain_handbook,
        "context_dir": pack.context_dir,
        "transcript": [],
    }
    context_ref = await mem.store_context_ref(debate_data)
    logger.info(f"Meeting initialized: {meeting_id} | ref={context_ref}")

    await notify_backend(
        {
            "meeting_type": "meeting_start",
            "meeting_id": meeting_id,
            "topic": topic,
            "context_ref": context_ref,
            "agents": [a["id"] for a in pack.agents],
            "time_limit_seconds": pack.time_limit,
            "timestamp": datetime.now().isoformat(),
        }
    )

    stop_event = asyncio.Event()
    monitor_task = asyncio.create_task(
        monitor_transcript(context_ref, stop_event, meeting_id)
    )

    template_phases = {p["id"]: p for p in pack.phases if "id" in p}
    phase1_config = template_phases.get("proposal")
    phase2_config = template_phases.get("discussion")

    try:
        ok = await run_phase_1(
            port_map[author["id"]],
            context_ref,
            meeting_id,
            topic,
            author_id=author["id"],
            proposal_sections=pack.proposal_sections,
            phase_config=phase1_config,
        )
        if not ok:
            logger.error("Phase 1 failed — aborting meeting")
            return

        await run_phase_2(
            port_map[facilitator["id"]],
            reviewer_ports,
            context_ref,
            meeting_id,
            pack.time_limit,
            pack.proposal_sections,
            author_port=port_map[author["id"]],
            author_id=author["id"],
            facilitator_id=facilitator["id"],
            phase_config=phase2_config,
        )

        phase3_ok = await run_phase_3(
            port_map[author["id"]],
            context_ref,
            meeting_id,
            author_id=author["id"],
        )
        if not phase3_ok:
            logger.warning(
                "Phase 3 failed — proceeding to governance with original proposal"
            )

        architect_port, resolved_architect_id = _resolve_architect_port(
            port_map, architect_id, reviewers
        )
        if architect_port is None:
            logger.error(
                "No architect or reviewer port available for Phase 4 governance — "
                "skipping governance (check roles in meeting_template.json / profiles.json)"
            )
            governance = {}
        else:
            governance_phase = pack.phase_by_number(4)
            governance = await run_phase_4(
                architect_port,
                port_map[facilitator["id"]],
                context_ref,
                meeting_id,
                architect_id=resolved_architect_id or "",
                facilitator_id=facilitator["id"],
                phase_config=governance_phase,
            )

        review_phase = pack.phase_by_number(5)
        review_content = {}
        if review_phase:
            review_model_alias = review_phase.get("model", "smart-agent")
            review_model = pack.model_map.get(review_model_alias, review_model_alias)
            review_schema = pack.schemas.get("FINAL_REVIEW")
            review_content = await run_phase_5(
                context_ref,
                meeting_id,
                governance,
                model=review_model,
                review_schema=review_schema,
                phase_config=review_phase,
            )
        else:
            logger.info("No Phase 5 (Final Review) configured — skipping")

        await write_outputs(
            context_ref,
            output_dir,
            meeting_id,
            governance,
            start_time,
            proposal_sections=pack.proposal_sections,
            schemas=pack.schemas,
            template_name=pack.template_name,
            review_content=review_content,
        )

    except asyncio.TimeoutError:
        logger.warning("Meeting timed out globally")
    except Exception as e:
        logger.exception(f"Meeting error: {e}")
    finally:
        stop_event.set()
        await asyncio.sleep(2)
        monitor_task.cancel()
        cleanup_nodes(processes)

        elapsed_final = time.time() - start_time
        finish_payload: dict = {
            "meeting_type": "meeting_finish",
            "meeting_id": meeting_id,
            "context_ref": context_ref,
            "elapsed_seconds": round(elapsed_final, 1),
            "timestamp": datetime.now().isoformat(),
        }
        try:
            finish_payload["architect_decision"] = governance.get("architect_decision")
            tx = await mem.get_context_ref(context_ref)
            finish_payload["total_turns"] = len((tx or {}).get("transcript", []))
        except Exception:
            pass
        await notify_backend(finish_payload)

    elapsed = time.time() - start_time
    logger.info(f"Meeting complete in {elapsed:.1f}s")
    print(f"\n--- Meeting Finished ({elapsed:.1f}s) ---")
    print(f"Output: {output_dir}")


# ── CLI Entry Point ───────────────────────────────────────────────────────


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Run a facilitated technical spike meeting"
    )
    parser.add_argument("--topic", type=str, required=True, help="Spike topic / title")
    parser.add_argument(
        "--context",
        type=str,
        default="",
        help="Path to domain context file or directory of .md files",
    )
    parser.add_argument("--output_dir", type=str, default="", help="Output directory")
    parser.add_argument(
        "--meeting-pack",
        type=str,
        default="",
        help="Path to meeting pack directory with profiles, prompts, schemas, template",
    )
    args = parser.parse_args()

    pack_dir = args.meeting_pack
    context_path = args.context

    from engine.pack_loader import load_context_handbook

    if not context_path and pack_dir:
        pack_context = Path(pack_dir) / "context"
        if pack_context.is_dir():
            context_path = str(pack_context)
            logger.info(f"Using default context from meeting pack: {context_path}")

    domain_handbook, context_dir = load_context_handbook(context_path)

    asyncio.run(
        run_meeting(
            args.topic, domain_handbook, context_dir, args.output_dir, pack_dir=pack_dir
        )
    )


if __name__ == "__main__":
    main()
