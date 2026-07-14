"""
Agent Loop — ReAct loop engine using native Bedrock Converse tool_use.

Each persona runs as an autonomous agent whose available tools are determined
by its ``skills`` list (from profiles.json).  The loop queries the tool
registry to build a persona-specific ``toolConfig``.

Agents with ``skills: []`` run tool-free (single-shot).

The loop is driven by Bedrock's ``stopReason``:
    - ``tool_use``  → execute requested tools, feed results back, continue
    - ``end_turn``  → extract final text, parse JSON, done
"""

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from agent_tools import (
    build_tool_config,
    build_tool_result_message,
    get_tool_descriptions,
)

logger = logging.getLogger("agent_loop")

_TOOL_NAME_INVALID = re.compile(r"[^a-zA-Z0-9_-]")


def _sanitize_assistant_msg(msg: dict[str, Any]) -> dict[str, Any]:
    """Scrub invalid chars from toolUse names so Bedrock won't reject the history."""
    for block in msg.get("content", []):
        tu = block.get("toolUse")
        if tu and "name" in tu:
            tu["name"] = _TOOL_NAME_INVALID.sub("", tu["name"].strip())
    return msg


RESPONSE_SCHEMA = """\
You MUST respond with ONLY a valid JSON object (no markdown fences, no extra text).
Use this exact schema:
{
  "sentiment": <int 1-5, where 1=very negative, 3=neutral, 5=very positive>,
  "would_use": <boolean>,
  "feedback": "<your honest feedback as this persona, 1-3 sentences>",
  "concerns": ["<concern 1>", "<concern 2>"],
  "feature_requests": ["<request 1>", "<request 2>"]
}
Keep "concerns" and "feature_requests" arrays short (0-3 items each).
Respond ONLY with the JSON object."""


@dataclass
class AgentResult:
    feedback_json: dict[str, Any]
    reasoning_trace: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: int = 0
    steps_used: int = 0
    total_latency_ms: int = 0
    model: str = ""
    skills: list[str] = field(default_factory=list)
    error: bool = False


def _build_system_prompt(persona: dict[str, Any]) -> str:
    skills = persona.get("skills", [])
    tool_descs = get_tool_descriptions(skills)

    lines = [
        "You are a simulated customer providing feedback on a new product feature.",
        f"Your persona: {persona['soul']}",
        f"Your response style: {persona['response_style']}",
        f"Your age: {persona['age']} | Tech level: {persona['tech_level']} | "
        f"Patience (1-10): {persona['patience']} | Language style: {persona['language_style']}",
        f"Your general satisfaction bias: {persona['satisfaction_bias']}",
    ]

    if persona.get("quirk"):
        lines.append(f"You are a {persona['quirk']}.")
    if persona.get("region"):
        lines.append(f"You are based in {persona['region']}.")
    if persona.get("tenure"):
        lines.append(f"Your account tenure: {persona['tenure']}.")
    if persona.get("plan"):
        lines.append(f"Your subscription: {persona['plan']}.")
    if persona.get("use_case"):
        lines.append(f"Primary use case: {persona['use_case']}.")
    if persona.get("emotional_state"):
        lines.append(f"Current mood: {persona['emotional_state']}.")

    if tool_descs:
        lines.append("")
        lines.append("## Your Tools")
        for td in tool_descs:
            lines.append(f"- **{td['name']}**: {td['description']}")

        lines.append(
            "\nUse your tools if it would help you form a more informed opinion. "
            "You decide when and what to search based on who you are and the feature being discussed."
        )
    else:
        lines.append("")
        lines.append(
            "You have no tools available. Rely on your own knowledge and instincts."
        )

    lines.append("")
    lines.append(
        "Stay fully in character. Do NOT break character or mention that you are an AI."
    )
    lines.append("Provide authentic, varied feedback as this specific person would.")
    lines.append("")
    lines.append(
        "IMPORTANT: When you have enough information to give your opinion, "
        "respond with ONLY the JSON feedback object below. Do NOT wrap it in "
        "markdown fences or add any extra text around the JSON."
    )
    lines.append("")
    lines.append(RESPONSE_SCHEMA)

    return "\n".join(lines)


def _build_user_prompt(feature_text: str, has_tools: bool) -> str:
    if has_tools:
        action = "You may use your tools to research if helpful, then provide"
    else:
        action = "Please provide"

    return (
        "--- FEATURE ANNOUNCEMENT ---\n\n"
        f"{feature_text}\n\n"
        "--- END ANNOUNCEMENT ---\n\n"
        f"Review this feature. {action} your honest JSON feedback."
    )


def _parse_json(raw: str) -> dict[str, Any] | None:
    text = raw.strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
    return None


class AgentPersonaRunner:
    """Runs a single persona through a ReAct loop on Bedrock Converse.

    The persona's ``skills`` list determines which tools are available.
    Personas with ``skills: []`` run as a single-shot call (no toolConfig).
    """

    def __init__(
        self,
        persona: dict[str, Any],
        feature_text: str,
        model: str,
        max_steps: int = 5,
        temperature: float = 0.8,
        max_tokens: int = 512,
    ):
        self.persona = persona
        self.feature_text = feature_text
        self.model = persona.get("_bedrock_model", model)
        self.max_steps = max_steps
        self.temperature = temperature
        self.max_tokens = max_tokens

        self.skills = persona.get("skills", [])
        self.tool_config = build_tool_config(self.skills)

        self.system_prompt = _build_system_prompt(persona)
        self.messages: list[dict[str, Any]] = []
        self.trace: list[dict[str, Any]] = []
        self.tool_calls = 0
        self._bedrock = None

    def _get_client(self):
        if self._bedrock is None:
            import boto3
            import os
            from botocore.config import Config as BotoConfig

            region = os.environ.get("AWS_DEFAULT_REGION", "ap-southeast-2")
            self._bedrock = boto3.client(
                "bedrock-runtime",
                region_name=region,
                config=BotoConfig(read_timeout=600, retries={"max_attempts": 2}),
            )
        return self._bedrock

    async def _converse(self, include_tools: bool = True) -> dict[str, Any]:
        bedrock = self._get_client()
        kwargs: dict[str, Any] = {
            "modelId": self.model,
            "system": [{"text": self.system_prompt}],
            "messages": self.messages,
            "inferenceConfig": {
                "maxTokens": self.max_tokens * 4,
                "temperature": self.temperature,
            },
        }
        if include_tools and self.tool_config is not None:
            kwargs["toolConfig"] = self.tool_config

        return await asyncio.get_event_loop().run_in_executor(
            None, lambda: bedrock.converse(**kwargs)
        )

    async def run(self) -> AgentResult:
        pid = self.persona["persona_id"]
        has_tools = self.tool_config is not None
        t0 = time.time()

        logger.info(
            f"[{pid}] Starting agent | skills={self.skills} | "
            f"tools={'yes' if has_tools else 'none'} | model={self.model}"
        )

        self.messages = [
            {
                "role": "user",
                "content": [{"text": _build_user_prompt(self.feature_text, has_tools)}],
            }
        ]

        for step in range(1, self.max_steps + 1):
            try:
                resp = await self._converse(include_tools=True)
            except Exception as e:
                err_str = str(e)
                logger.error(f"[{pid}] Bedrock error step {step}: {e}")
                if (
                    "toolUse.name" in err_str
                    and "failed to satisfy constraint" in err_str
                ):
                    logger.warning(
                        f"[{pid}] Malformed tool name in history — scrubbing and retrying"
                    )
                    for msg in self.messages:
                        _sanitize_assistant_msg(msg)
                await asyncio.sleep(2)
                continue

            stop_reason = resp.get("stopReason", "")
            latency = resp.get("metrics", {}).get("latencyMs", 0)
            assistant_msg = _sanitize_assistant_msg(resp["output"]["message"])
            self.messages.append(assistant_msg)

            self.trace.append(
                {
                    "step": step,
                    "stop_reason": stop_reason,
                    "latency_ms": latency,
                }
            )

            if stop_reason == "tool_use":
                tool_blocks = [c for c in assistant_msg["content"] if c.get("toolUse")]
                result = build_tool_result_message(tool_blocks)
                self.messages.append(result["message"])
                self.tool_calls += len(tool_blocks)

                for t in result["traces"]:
                    self.trace[-1].setdefault("tools", []).append(t)

                logger.info(
                    f"[{pid}] Step {step}: tool_use ({len(tool_blocks)} call(s)) "
                    f"[{self.model}]"
                )
                continue

            if stop_reason == "end_turn":
                text_parts = [
                    c["text"] for c in assistant_msg["content"] if c.get("text")
                ]
                raw_text = "\n".join(text_parts)
                parsed = _parse_json(raw_text)
                if parsed and "sentiment" in parsed:
                    elapsed = int((time.time() - t0) * 1000)
                    logger.info(
                        f"[{pid}] Step {step}: end_turn → sentiment={parsed['sentiment']} "
                        f"tools={self.tool_calls} [{self.model}] {elapsed}ms"
                    )
                    return AgentResult(
                        feedback_json=parsed,
                        reasoning_trace=self.trace,
                        tool_calls=self.tool_calls,
                        steps_used=step,
                        total_latency_ms=elapsed,
                        model=self.model,
                        skills=self.skills,
                    )
                logger.warning(
                    f"[{pid}] Step {step}: end_turn but invalid JSON, forcing retry"
                )

        logger.warning(f"[{pid}] Max steps reached, forcing final answer")
        self.messages.append(
            {
                "role": "user",
                "content": [
                    {"text": "Please respond now with ONLY the JSON feedback object."}
                ],
            }
        )
        try:
            resp = await self._converse(include_tools=False)
            assistant_msg = resp["output"]["message"]
            text_parts = [c["text"] for c in assistant_msg["content"] if c.get("text")]
            raw_text = "\n".join(text_parts)
            parsed = _parse_json(raw_text)
            if parsed and "sentiment" in parsed:
                elapsed = int((time.time() - t0) * 1000)
                return AgentResult(
                    feedback_json=parsed,
                    reasoning_trace=self.trace,
                    tool_calls=self.tool_calls,
                    steps_used=self.max_steps + 1,
                    total_latency_ms=elapsed,
                    model=self.model,
                    skills=self.skills,
                )
        except Exception as e:
            logger.error(f"[{pid}] Final forced call failed: {e}")

        elapsed = int((time.time() - t0) * 1000)
        return AgentResult(
            feedback_json={
                "sentiment": 3,
                "would_use": False,
                "feedback": "[Agent failed to produce valid JSON after max steps]",
                "concerns": [],
                "feature_requests": [],
            },
            reasoning_trace=self.trace,
            tool_calls=self.tool_calls,
            steps_used=self.max_steps + 1,
            total_latency_ms=elapsed,
            model=self.model,
            skills=self.skills,
            error=True,
        )
