"""
Marketing Researcher Agent — Two-turn agent in the research pipeline.

Turn 1 (design_survey): Reads PO research brief, generates structured survey.json
Turn 2 (compile_findings): Reads survey_responses.json, interprets data, writes marketing_report.md

Persona loaded from analysts.json. Supports agentic mode (web_search) via Bedrock Converse.

Usage (standalone):
    python marketing_agent.py design-survey --brief path/to/research_brief.md --run-dir output/run_XXX
    python marketing_agent.py compile --responses path/to/survey_responses.json --run-dir output/run_XXX
"""

import os
import json
import asyncio
import logging
import argparse
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from pe_layout import ensure_sys_path, load_dotenv_layers

ensure_sys_path()
load_dotenv_layers()

try:
    import boto3
    from botocore.config import Config as BotoConfig
except ImportError:
    boto3 = None  # type: ignore[assignment]
    BotoConfig = None  # type: ignore[assignment,misc]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [marketing] - %(levelname)s - %(message)s",
)
logger = logging.getLogger("marketing_agent")

SKILL_ROOT = Path(__file__).resolve().parent.parent
ANALYSTS_JSON = SKILL_ROOT / "analysts.json"

BEDROCK_REGION = os.environ.get("AWS_DEFAULT_REGION", "ap-southeast-2")
BEDROCK_TIMEOUT = (
    BotoConfig(read_timeout=600, retries={"max_attempts": 2}) if BotoConfig else None
)


def _get_bedrock_client():
    if not hasattr(_get_bedrock_client, "_client"):
        _get_bedrock_client._client = boto3.client(
            "bedrock-runtime", region_name=BEDROCK_REGION, config=BEDROCK_TIMEOUT
        )
    return _get_bedrock_client._client


def load_analyst(
    analyst_id: str = "marketing_researcher",
) -> tuple[dict[str, Any], dict[str, Any]]:
    config = json.loads(ANALYSTS_JSON.read_text(encoding="utf-8"))
    defaults = config.get("defaults", {})
    for analyst in config.get("analysts", []):
        if analyst["id"] == analyst_id:
            return analyst, defaults
    available = [a["id"] for a in config.get("analysts", [])]
    raise ValueError(f"Analyst '{analyst_id}' not found. Available: {available}")


def _build_survey_design_prompt(
    analyst: dict[str, Any], include_tools: bool = False
) -> str:
    tools_block = ""
    if include_tools:
        skills = analyst.get("skills", [])
        if skills:
            from agent_tools import get_tool_descriptions

            tool_descs = get_tool_descriptions(skills)
            if tool_descs:
                tools_block = "\n## Your Tools\n"
                for td in tool_descs:
                    tools_block += f"- **{td['name']}**: {td['description']}\n"
                tools_block += (
                    "\nUse tools to check competitor offerings or best practices "
                    "before designing your survey. You decide what to search based on the feature.\n"
                )

    design_sections = analyst.get("survey_design_sections", [])
    sections_note = ""
    if design_sections:
        sections_note = "\nBefore the JSON, include:\n"
        for s in design_sections:
            sections_note += f"- **{s['heading']}**: {s['instructions']}\n"

    return (
        f"You are a {analyst['label']}.\n\n"
        f"{analyst['soul']}\n\n"
        f"Your communication style: {analyst['style']}\n"
        f"{tools_block}\n"
        f"A Product Owner has commissioned you to design a customer survey for a new feature.\n"
        f"You will receive the PO's research brief. Your job is to design a survey that will "
        f"collect the data needed to answer the PO's research questions.\n\n"
        f"Your survey MUST be output as a JSON object with this exact schema:\n"
        f"{{\n"
        f'  "title": "Survey title",\n'
        f'  "intro": "Brief context paragraph for respondents (2-3 sentences)",\n'
        f'  "questions": [\n'
        f'    {{ "id": "q1", "type": "rating", "text": "Question text", "scale_min": 1, "scale_max": 5, "scale_labels": ["Not at all likely", "Extremely likely"] }},\n'
        f'    {{ "id": "q2", "type": "multiple_choice", "text": "Question text", "options": ["Option A", "Option B", "Option C"], "allow_multiple": false }},\n'
        f'    {{ "id": "q3", "type": "open", "text": "Open-ended question text" }}\n'
        f"  ]\n"
        f"}}\n\n"
        f"Design 6-10 questions. Mix question types:\n"
        f"- 2-3 **rating** questions (satisfaction, likelihood, importance)\n"
        f"- 2-3 **multiple_choice** questions (preferences, priorities)\n"
        f"- 2-3 **open** questions (concerns, suggestions, detailed feedback)\n\n"
        f"Order questions from easy (ratings) to harder (open-ended).\n"
        f"Avoid leading questions. Keep language simple and direct.\n"
        f"{sections_note}\n"
        f"Output the rationale first, then the JSON block wrapped in ```json fences.\n\n"
        f"{analyst.get('persona_instructions', '')}"
    )


def _build_compilation_prompt(
    analyst: dict[str, Any], include_tools: bool = False
) -> str:
    tools_block = ""
    if include_tools:
        skills = analyst.get("skills", [])
        if skills:
            from agent_tools import get_tool_descriptions

            tool_descs = get_tool_descriptions(skills)
            if tool_descs:
                tools_block = "\n## Your Tools\n"
                for td in tool_descs:
                    tools_block += f"- **{td['name']}**: {td['description']}\n"
                tools_block += (
                    "\nUse tools to look up competitor context or industry benchmarks "
                    "to enrich your analysis. You decide what to search based on the data.\n"
                )

    compilation_sections = analyst.get("compilation_sections", [])
    sections_block = ""
    if compilation_sections:
        sections_block = (
            "\nYour report MUST include these sections (use markdown headings):\n"
        )
        for s in compilation_sections:
            sections_block += f"\n## {s['heading']}\n{s['instructions']}\n"

    return (
        f"You are a {analyst['label']}.\n\n"
        f"{analyst['soul']}\n\n"
        f"Your communication style: {analyst['style']}\n"
        f"{tools_block}\n"
        f"You have just collected survey responses from simulated customers. "
        f"Your job is to analyze the raw data and produce a comprehensive research report "
        f"for the Product Owner.\n\n"
        f"Interpret themes and patterns. Don't just recite numbers -- explain what they mean "
        f"for the product. Use direct quotes from open-ended responses to anchor findings.\n"
        f"{sections_block}\n"
        f"Output clean markdown. Do NOT wrap in JSON.\n\n"
        f"{analyst.get('persona_instructions', '')}"
    )


_TOOL_NAME_INVALID = re.compile(r"[^a-zA-Z0-9_-]")


def _sanitize_assistant_msg(msg: dict[str, Any]) -> dict[str, Any]:
    """Scrub invalid chars from toolUse names so Bedrock won't reject the history."""
    for block in msg.get("content", []):
        tu = block.get("toolUse")
        if tu and "name" in tu:
            tu["name"] = _TOOL_NAME_INVALID.sub("", tu["name"].strip())
    return msg


def _coalesce_consecutive_roles(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge adjacent messages with the same role to avoid Mistral's
    'last message is from the assistant' validation error.

    Builds new dicts with copied content lists so the caller's persistent
    message history is never mutated — previously this aliased messages[0] and
    re-extended it on every step, growing the request unboundedly.
    """
    out: list[dict[str, Any]] = []
    for msg in messages:
        if out and msg["role"] == out[-1]["role"]:
            merged = dict(out[-1])
            merged["content"] = [*out[-1]["content"], *msg.get("content", [])]
            out[-1] = merged
        else:
            out.append({**msg, "content": list(msg.get("content", []))})
    return out


async def _call_bedrock_agentic(
    system_prompt: str,
    user_prompt: str,
    model: str,
    temperature: float,
    max_tokens: int,
    skills: list[str],
    max_steps: int = 5,
    label: str = "Marketing",
) -> str | None:
    if boto3 is None:
        logger.error("boto3 not installed")
        return None

    from agent_tools import build_tool_config, build_tool_result_message

    bedrock = _get_bedrock_client()
    tool_config = build_tool_config(skills)
    has_tools = tool_config is not None
    total_tool_calls = 0

    messages: list[dict[str, Any]] = [
        {"role": "user", "content": [{"text": user_prompt}]}
    ]

    for step in range(1, max_steps + 1):
        safe_messages = _coalesce_consecutive_roles(messages)
        kwargs: dict[str, Any] = {
            "modelId": model,
            "system": [{"text": system_prompt}],
            "messages": safe_messages,
            "inferenceConfig": {
                "maxTokens": max_tokens,
                "temperature": temperature,
            },
        }
        if has_tools:
            kwargs["toolConfig"] = tool_config

        try:
            resp = await asyncio.get_event_loop().run_in_executor(
                None, lambda: bedrock.converse(**kwargs)
            )
        except Exception as e:
            if "Throttling" in str(type(e).__name__):
                wait = 5 * step
                logger.warning(
                    f"[{label}] Bedrock throttled step {step}. Waiting {wait}s..."
                )
                await asyncio.sleep(wait)
                continue

            err_str = str(e)
            logger.error(f"[{label}] Bedrock error step {step}: {e}")

            if (
                "add_generation_prompt" in err_str
                or "last message is from the assistant" in err_str
            ):
                logger.warning(
                    f"[{label}] Detected Mistral message format bug — recovering by forcing user turn"
                )
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "text": "Please continue with your analysis and produce the final output."
                            }
                        ],
                    }
                )
            elif (
                "toolUse.name" in err_str and "failed to satisfy constraint" in err_str
            ):
                logger.warning(
                    f"[{label}] Malformed tool name in history — scrubbing and retrying"
                )
                for msg in messages:
                    _sanitize_assistant_msg(msg)

            await asyncio.sleep(3)
            continue

        stop_reason = resp.get("stopReason", "")
        assistant_msg = _sanitize_assistant_msg(resp["output"]["message"])
        messages.append(assistant_msg)

        if stop_reason == "tool_use":
            tool_blocks = [c for c in assistant_msg["content"] if c.get("toolUse")]
            result = build_tool_result_message(tool_blocks)
            messages.append(result["message"])
            total_tool_calls += len(tool_blocks)
            logger.info(
                f"[{label}] Step {step}: tool_use ({len(tool_blocks)} call(s)) "
                f"[{model}] (total: {total_tool_calls})"
            )
            continue

        if stop_reason == "end_turn":
            text_parts = [c["text"] for c in assistant_msg["content"] if c.get("text")]
            raw_text = "\n".join(text_parts)
            logger.info(
                f"[{label}] Step {step}: end_turn | tools={total_tool_calls} [{model}]"
            )
            return raw_text

    logger.warning(f"[{label}] Max steps reached, forcing final answer")
    messages.append(
        {
            "role": "user",
            "content": [{"text": "Please produce your final output now."}],
        }
    )
    try:
        kwargs_final: dict[str, Any] = {
            "modelId": model,
            "system": [{"text": system_prompt}],
            "messages": messages,
            "inferenceConfig": {"maxTokens": max_tokens, "temperature": temperature},
        }
        resp = await asyncio.get_event_loop().run_in_executor(
            None, lambda: bedrock.converse(**kwargs_final)
        )
        text_parts = [
            c["text"] for c in resp["output"]["message"]["content"] if c.get("text")
        ]
        return "\n".join(text_parts)
    except Exception as e:
        logger.error(f"[{label}] Final forced call failed: {e}")
    return None


async def _call_bedrock_single(
    system_prompt: str,
    user_prompt: str,
    model: str,
    temperature: float,
    max_tokens: int,
    label: str = "Marketing",
) -> str | None:
    if boto3 is None:
        logger.error("boto3 not installed")
        return None

    bedrock = _get_bedrock_client()
    for attempt in range(3):
        try:
            resp = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: bedrock.converse(
                    modelId=model,
                    system=[{"text": system_prompt}],
                    messages=[{"role": "user", "content": [{"text": user_prompt}]}],
                    inferenceConfig={
                        "maxTokens": max_tokens,
                        "temperature": temperature,
                    },
                ),
            )
            return resp["output"]["message"]["content"][0]["text"]
        except Exception as e:
            if "Throttling" in str(type(e).__name__):
                wait = 5 * (attempt + 1)
                logger.warning(f"[{label}] Bedrock throttled. Waiting {wait}s...")
                await asyncio.sleep(wait)
            else:
                logger.error(f"[{label}] Bedrock error (attempt {attempt + 1}): {e}")
                await asyncio.sleep(3)
    return None


def _extract_json_from_text(text: str) -> dict[str, Any] | None:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    json_match = re.search(r"```json\s*\n(.*?)\n```", text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    return None


async def design_survey(
    brief_path: Path,
    run_dir: Path,
    analyst_id: str = "marketing_researcher",
    backend: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    agentic: bool = True,
    max_steps: int = 5,
) -> Path:
    """Marketing Turn 1: Read PO brief, generate survey.json."""
    analyst, defaults = load_analyst(analyst_id)

    resolved_model = model or defaults.get(
        "model", "mistral.mistral-large-3-675b-instruct"
    )
    resolved_backend = backend or defaults.get("backend", "bedrock")
    resolved_temperature = (
        temperature if temperature is not None else defaults.get("temperature", 0.4)
    )
    resolved_max_tokens = (
        max_tokens if max_tokens is not None else defaults.get("max_tokens", 4096)
    )

    skills = analyst.get("skills", [])
    use_agentic = agentic and bool(skills) and resolved_backend == "bedrock"

    brief_text = brief_path.read_text(encoding="utf-8")
    system_prompt = _build_survey_design_prompt(analyst, include_tools=use_agentic)

    user_prompt = (
        "# PRODUCT OWNER RESEARCH BRIEF\n\n"
        f"{brief_text}\n\n"
        "---\n\n"
        "Based on this brief, design a customer survey. "
        "Output your rationale first, then the survey JSON in ```json fences."
    )

    logger.info(
        f"[{analyst['label']}] Designing survey | "
        f"mode={'agentic' if use_agentic else 'single-shot'} | "
        f"model={resolved_model}"
    )

    if use_agentic:
        raw_text = await _call_bedrock_agentic(
            system_prompt,
            user_prompt,
            resolved_model,
            resolved_temperature,
            resolved_max_tokens,
            skills,
            max_steps,
            analyst["label"],
        )
    else:
        raw_text = await _call_bedrock_single(
            system_prompt,
            user_prompt,
            resolved_model,
            resolved_temperature,
            resolved_max_tokens,
            analyst["label"],
        )

    if not raw_text:
        raise RuntimeError(f"{analyst['label']} survey design LLM call failed")

    survey_data = _extract_json_from_text(raw_text)
    if not survey_data or "questions" not in survey_data:
        raise RuntimeError(
            f"{analyst['label']} failed to produce valid survey JSON. "
            f"Raw output (first 500 chars): {raw_text[:500]}"
        )

    survey_path = run_dir / "survey.json"
    survey_path.write_text(json.dumps(survey_data, indent=2), encoding="utf-8")

    rationale_path = run_dir / "survey_rationale.md"
    rationale_header = (
        f"# Survey Design Rationale\n\n"
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"**Agent:** {analyst['label']}\n"
        f"**Model:** {resolved_model}\n"
        f"**Questions:** {len(survey_data['questions'])}\n\n---\n\n"
    )
    rationale_path.write_text(rationale_header + raw_text, encoding="utf-8")

    logger.info(
        f"[{analyst['label']}] Survey designed: {len(survey_data['questions'])} questions -> {survey_path}"
    )
    return survey_path


async def compile_findings(
    run_dir: Path,
    analyst_id: str = "marketing_researcher",
    backend: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    agentic: bool = True,
    max_steps: int = 5,
) -> Path:
    """Marketing Turn 2: Read survey responses, produce marketing_report.md."""
    analyst, defaults = load_analyst(analyst_id)

    resolved_model = model or defaults.get(
        "model", "mistral.mistral-large-3-675b-instruct"
    )
    resolved_backend = backend or defaults.get("backend", "bedrock")
    resolved_temperature = (
        temperature if temperature is not None else defaults.get("temperature", 0.4)
    )
    resolved_max_tokens = (
        max_tokens if max_tokens is not None else defaults.get("max_tokens", 4096)
    )

    skills = analyst.get("skills", [])
    use_agentic = agentic and bool(skills) and resolved_backend == "bedrock"

    responses_path = run_dir / "survey_responses.json"
    if not responses_path.exists():
        raise FileNotFoundError(f"No survey_responses.json in {run_dir}")
    responses = json.loads(responses_path.read_text(encoding="utf-8"))

    survey_path = run_dir / "survey.json"
    survey_data: dict[str, Any] = {}
    if survey_path.exists():
        survey_data = json.loads(survey_path.read_text(encoding="utf-8"))

    feature_text = ""
    feature_path = run_dir / "feature.txt"
    if feature_path.exists():
        feature_text = feature_path.read_text(encoding="utf-8")

    brief_text = ""
    brief_path = run_dir / "research_brief.md"
    if brief_path.exists():
        brief_text = brief_path.read_text(encoding="utf-8")

    system_prompt = _build_compilation_prompt(analyst, include_tools=use_agentic)

    valid = [r for r in responses if not r.get("error")]
    user_parts = []

    if feature_text:
        user_parts.append(f"# FEATURE UNDER REVIEW\n\n{feature_text.strip()}\n")

    if brief_text:
        user_parts.append(f"# PO RESEARCH BRIEF\n\n{brief_text.strip()}\n")

    if survey_data:
        user_parts.append(
            f"# SURVEY DESIGN\n\nTitle: {survey_data.get('title', 'N/A')}"
        )
        user_parts.append(f"Questions: {len(survey_data.get('questions', []))}\n")
        for q in survey_data.get("questions", []):
            user_parts.append(f"- [{q['id']}] ({q['type']}) {q['text']}")
        user_parts.append("")

    user_parts.append(f"# SURVEY RESPONSES ({len(valid)} respondents)\n")
    for r in valid:
        entry = f"## [{r.get('archetype_label', '?')}] {r.get('persona_id', '?')}\n"
        for answer in r.get("answers", []):
            qid = answer.get("question_id", "?")
            val = answer.get("value", "")
            if isinstance(val, list):
                val = ", ".join(str(v) for v in val)
            entry += f"- **{qid}**: {val}\n"
        user_parts.append(entry)

    user_parts.append(
        "\n---\nBased on all the above data, produce your research report in markdown."
    )

    user_prompt = "\n".join(user_parts)

    logger.info(
        f"[{analyst['label']}] Compiling findings from {len(valid)} responses | "
        f"mode={'agentic' if use_agentic else 'single-shot'} | model={resolved_model}"
    )

    if use_agentic:
        raw_text = await _call_bedrock_agentic(
            system_prompt,
            user_prompt,
            resolved_model,
            resolved_temperature,
            resolved_max_tokens,
            skills,
            max_steps,
            analyst["label"],
        )
    else:
        raw_text = await _call_bedrock_single(
            system_prompt,
            user_prompt,
            resolved_model,
            resolved_temperature,
            resolved_max_tokens,
            analyst["label"],
        )

    if not raw_text:
        raw_text = f"*{analyst['label']} compilation failed. LLM returned no output.*"

    header = (
        f"# Marketing Research Report\n\n"
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"**Agent:** {analyst['label']}\n"
        f"**Model:** {resolved_model}\n"
        f"**Mode:** {'agentic' if use_agentic else 'single-shot'}\n"
        f"**Respondents:** {len(valid)}\n\n---\n\n"
    )

    report_path = run_dir / "marketing_report.md"
    report_path.write_text(header + raw_text, encoding="utf-8")

    logger.info(f"[{analyst['label']}] Report saved -> {report_path}")
    return report_path


def main():
    parser = argparse.ArgumentParser(description="Marketing Researcher Agent")
    subparsers = parser.add_subparsers(dest="command", required=True)

    design_parser = subparsers.add_parser(
        "design-survey", help="Design a survey from PO brief"
    )
    design_parser.add_argument(
        "--brief", type=str, required=True, help="Path to research_brief.md"
    )
    design_parser.add_argument(
        "--run-dir", type=str, required=True, help="Output run directory"
    )
    design_parser.add_argument("--model", type=str, default=None)
    design_parser.add_argument(
        "--no-agentic", dest="agentic", action="store_false", default=True
    )
    design_parser.add_argument("--max-steps", type=int, default=5)

    compile_parser = subparsers.add_parser(
        "compile", help="Compile findings from survey responses"
    )
    compile_parser.add_argument(
        "--run-dir",
        type=str,
        required=True,
        help="Run directory with survey_responses.json",
    )
    compile_parser.add_argument("--model", type=str, default=None)
    compile_parser.add_argument(
        "--no-agentic", dest="agentic", action="store_false", default=True
    )
    compile_parser.add_argument("--max-steps", type=int, default=5)

    args = parser.parse_args()

    if args.command == "design-survey":
        path = asyncio.run(
            design_survey(
                brief_path=Path(args.brief),
                run_dir=Path(args.run_dir),
                model=args.model,
                agentic=args.agentic,
                max_steps=args.max_steps,
            )
        )
        print(f"\nSurvey designed -> {path}")

    elif args.command == "compile":
        path = asyncio.run(
            compile_findings(
                run_dir=Path(args.run_dir),
                model=args.model,
                agentic=args.agentic,
                max_steps=args.max_steps,
            )
        )
        print(f"\nReport compiled -> {path}")


if __name__ == "__main__":
    main()
