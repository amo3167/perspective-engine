"""
Analyst Agent — Data-driven persona that synthesizes raw customer feedback
into a strategic research report with recommendations.

Analyst personas are defined in analysts.json (alongside profiles.json).
Runs as an ephemeral LLM call (same pattern as the customer persona agents).

Usage:
    python po_analyst.py --run-dir output/run_YYYYMMDD_HHMMSS
    python po_analyst.py --run-dir output/run_YYYYMMDD_HHMMSS --analyst product_owner
    python po_analyst.py --run-dir output/run_YYYYMMDD_HHMMSS --backend bedrock --model mistral.mistral-large-3-675b-instruct
    python po_analyst.py --run-dir output/run_YYYYMMDD_HHMMSS --dry-run
"""

import sys
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
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment]

try:
    import boto3
except ImportError:
    boto3 = None  # type: ignore[assignment]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [po_analyst] - %(levelname)s - %(message)s",
)
logger = logging.getLogger("po_analyst")

SKILL_ROOT = Path(__file__).resolve().parent.parent
ANALYSTS_JSON = SKILL_ROOT / "analysts.json"


def load_analysts() -> dict[str, Any]:
    if not ANALYSTS_JSON.exists():
        raise FileNotFoundError(f"analysts.json not found at {ANALYSTS_JSON}")
    return json.loads(ANALYSTS_JSON.read_text(encoding="utf-8"))


def get_analyst(analyst_id: str) -> dict[str, Any]:
    config = load_analysts()
    for analyst in config.get("analysts", []):
        if analyst["id"] == analyst_id:
            return analyst
    available = [a["id"] for a in config.get("analysts", [])]
    raise ValueError(f"Analyst '{analyst_id}' not found. Available: {available}")


def get_analyst_defaults() -> dict[str, Any]:
    config = load_analysts()
    return config.get("defaults", {})


def build_system_prompt(analyst: dict[str, Any], include_tools: bool = False) -> str:
    sections_block = ""
    for section in analyst.get("report_sections", []):
        sections_block += f"\n## {section['heading']}\n{section['instructions']}\n"

    focus = analyst.get("focus_areas", [])
    focus_block = ""
    if focus:
        focus_block = (
            "\nYour key focus areas:\n" + "\n".join(f"- {f}" for f in focus) + "\n"
        )

    persona_instructions = analyst.get(
        "persona_instructions",
        f"Stay in character as a {analyst['label']}. Be opinionated. Make clear calls. Back them with the data provided.",
    )

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
                    "\nUse your tools to validate assumptions, check competitor benchmarks, "
                    "or look up compliance requirements before making recommendations. "
                    "You decide what to search based on the feature and data provided.\n"
                    "\nAfter researching, produce your full markdown report. "
                    "Do NOT wrap your final report in JSON -- output clean markdown.\n"
                )

    return (
        f"You are a {analyst['label']}.\n\n"
        f"{analyst['soul']}\n\n"
        f"Your communication style: {analyst['style']}\n"
        f"{focus_block}"
        f"{tools_block}\n"
        f"You have just received the results of a simulated customer feedback study. "
        f"Your job is to analyze all the data and produce an executive research report "
        f"with clear, actionable recommendations.\n\n"
        f"Your report MUST include these sections (use markdown headings):\n"
        f"{sections_block}\n"
        f"{persona_instructions}"
    )


def _build_user_prompt(
    feature_text: str,
    stats: dict[str, Any],
    responses: list[dict[str, Any]],
    feedback_report: str | None = None,
) -> str:
    response_summaries = []
    for r in responses:
        if r.get("error"):
            continue
        entry = (
            f"[{r.get('archetype_label', '?')}] "
            f"sentiment={r.get('sentiment')}/5 would_use={r.get('would_use')} "
            f"| {r.get('feedback', '')}"
        )
        concerns = r.get("concerns", [])
        if concerns:
            entry += f" | concerns: {', '.join(concerns)}"
        requests = r.get("feature_requests", [])
        if requests:
            entry += f" | requests: {', '.join(requests)}"
        response_summaries.append(entry)

    parts = [
        "# FEATURE UNDER REVIEW\n",
        feature_text.strip(),
        "\n\n# QUANTITATIVE SUMMARY\n",
        f"- Total respondents: {stats.get('total', len(responses))}",
        f"- Average sentiment: {stats.get('avg_sentiment', 'N/A'):.1f}/5.0"
        if isinstance(stats.get("avg_sentiment"), (int, float))
        else f"- Average sentiment: {stats.get('avg_sentiment', 'N/A')}",
        f"- Would-use rate: {stats.get('would_use_pct', 'N/A'):.0f}%"
        if isinstance(stats.get("would_use_pct"), (int, float))
        else f"- Would-use rate: {stats.get('would_use_pct', 'N/A')}",
        f"- Error responses: {stats.get('errors', 0)}",
    ]

    sentiment_dist = stats.get("sentiment_dist", {})
    if sentiment_dist:
        parts.append("\nSentiment distribution:")
        for score in range(1, 6):
            count = sentiment_dist.get(str(score), sentiment_dist.get(score, 0))
            label = {
                1: "Very Negative",
                2: "Negative",
                3: "Neutral",
                4: "Positive",
                5: "Very Positive",
            }.get(score, "?")
            parts.append(f"  {score} ({label}): {count}")

    top_concerns = stats.get("top_concerns", [])
    if top_concerns:
        parts.append("\nTop concerns (by frequency):")
        for item in top_concerns[:10]:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                parts.append(f"  - {item[0]} ({item[1]}x)")
            else:
                parts.append(f"  - {item}")

    top_requests = stats.get("top_requests", [])
    if top_requests:
        parts.append("\nTop feature requests (by frequency):")
        for item in top_requests[:10]:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                parts.append(f"  - {item[0]} ({item[1]}x)")
            else:
                parts.append(f"  - {item}")

    parts.append("\n\n# INDIVIDUAL RESPONSES\n")
    parts.extend(response_summaries)

    if feedback_report:
        parts.append("\n\n# STATISTICAL REPORT (for reference)\n")
        parts.append(feedback_report)

    parts.append("\n\n---\nBased on all the above data, produce your research report.")

    return "\n".join(parts)


DRY_RUN_REPORT = """\
## Executive Summary

Based on the simulated customer feedback, this feature shows **moderate promise** with a
70% would-use rate but a polarized sentiment distribution (avg 3.0/5). The feature is
**conditionally shippable** with targeted modifications for accessibility and UX simplicity.

## Key Findings

1. **Accessibility is a cross-cutting blocker** -- Accessibility Advocate, Enterprise Admin,
   and Privacy Skeptic archetypes all independently flagged gaps in screen reader support,
   keyboard navigation, and WCAG compliance. This isn't a niche concern.

2. **Complexity anxiety spans 3 segments** -- Newcomers, Change Resistant, and Casual Users
   all expressed concern about feature overload. A "simple mode" was the most consistent
   unprompted request across segments.

3. **Power users and data analysts want API access, not dashboards** -- Both segments scored
   low on sentiment because they see this as a visual tool when they need programmatic access.
   The dashboard itself isn't wrong -- it's just not sufficient for this segment.

4. **Privacy concerns are conditional, not absolute** -- Privacy Skeptics didn't reject the
   feature outright. They want transparency (data storage, retention, third-party sharing).
   A clear data policy page would likely convert this segment.

5. **Early Adopters are enthusiastic evangelists** -- Highest sentiment (4.5/5) and already
   suggesting improvements (benchmark overlays, shareable links). These are your launch-day
   champions.

## Risk Assessment

| Risk | Severity | Affected Segments | Mitigation |
|------|----------|-------------------|------------|
| Accessibility non-compliance | **High** | All (legal exposure) | WCAG 2.2 audit before launch |
| Feature overwhelm -> low adoption | **Medium** | Newcomer, Casual, Change Resistant (60% of base) | Ship with simple/advanced toggle |
| Power user churn | **Low** | Power User, Data Analyst (18% of base) | API endpoints in fast-follow |
| Privacy backlash | **Medium** | Privacy Skeptic (15%) | Data policy page at launch |

## Recommendations

### Launch Blockers
- **WCAG 2.2 compliance audit + fixes** -- ARIA labels on charts, keyboard nav, high-contrast mode. Effort: **L**. Non-negotiable for a financial tool.
- **Simple/Advanced mode toggle** -- Default to simple view with option to expand. Effort: **M**. Addresses 60% of the user base's primary concern.

### Fast Follows (within 2 weeks)
- **Data privacy policy page** -- Specific to dashboard data handling. Effort: **S**. Unblocks Privacy Skeptics.
- **Guided walkthrough for first-time users** -- Interactive tour of key features. Effort: **M**. Reduces newcomer abandonment.

### Backlog
- **REST API for dashboard data** -- JSON/Parquet export, webhook support. Effort: **L**. Wins back Power Users and Data Analysts.
- **Shareable report links** -- OG preview cards, privacy filter. Effort: **M**. Amplifies Early Adopter evangelism.
- **RBAC for enterprise** -- Role-based widget access. Effort: **L**. Enterprise deal enabler.

## Segment Strategy

| Segment | Current Sentiment | Strategy |
|---------|-------------------|----------|
| Change Resistant (1.5/5) | **Accept partial loss.** Keep old P&L view accessible as "Classic View" during transition. Don't force migration. |
| Privacy Skeptic (2.0/5) | **Win with transparency.** Privacy policy + data deletion option converts this segment. |
| Accessibility Advocate (2.0/5) | **Fix at launch.** This is a legal and ethical requirement, not optional. |
| Data-Driven Analyst (2.0/5) | **Defer to fast-follow.** API access is the unlock -- dashboard alone won't satisfy them. |

## Go/No-Go Verdict

**Conditional GO** -- ship after addressing these conditions:
1. WCAG 2.2 minimum compliance verified
2. Simple/Advanced mode toggle implemented
3. "Classic View" opt-out available for existing users

Expected adoption with these changes: **80-85%** (up from current 70%).\
"""


def _build_brief_system_prompt(
    analyst: dict[str, Any], include_tools: bool = False
) -> str:
    """System prompt for PO Turn 1: writing a research brief for Marketing."""
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
                    "\nUse tools to inform your brief with competitive context. "
                    "You decide what to search based on the feature being reviewed.\n"
                )

    brief_sections = analyst.get("brief_sections", [])
    sections_block = ""
    if brief_sections:
        sections_block = (
            "\nYour brief MUST include these sections (use markdown headings):\n"
        )
        for s in brief_sections:
            sections_block += f"\n## {s['heading']}\n{s['instructions']}\n"

    return (
        f"You are a {analyst['label']}.\n\n"
        f"{analyst['soul']}\n\n"
        f"Your communication style: {analyst['style']}\n"
        f"{tools_block}\n"
        f"You are commissioning a Marketing Researcher to run a customer survey "
        f"on a new feature. Your job is to write a research brief that tells the "
        f"Marketing Researcher exactly what to investigate.\n\n"
        f"Be specific about what you need to learn. Focus on adoption risk, "
        f"segment fit, and the questions that will determine your go/no-go decision.\n"
        f"{sections_block}\n"
        f"Output clean markdown. Be concise and actionable.\n\n"
        f"{analyst.get('persona_instructions', '')}"
    )


def _build_survey_user_prompt(
    feature_text: str,
    survey_data: dict[str, Any],
    survey_responses: list[dict[str, Any]],
    marketing_report: str | None = None,
    research_brief: str | None = None,
) -> str:
    """Build user prompt for PO Turn 2 when analyzing survey-based data."""
    valid = [r for r in survey_responses if not r.get("error")]

    parts = ["# FEATURE UNDER REVIEW\n", feature_text.strip(), ""]

    if research_brief:
        parts.append("# YOUR ORIGINAL RESEARCH BRIEF\n")
        parts.append(research_brief.strip())
        parts.append("")

    if survey_data:
        parts.append("# SURVEY DESIGN\n")
        parts.append(f"Title: {survey_data.get('title', 'N/A')}")
        parts.append(f"Questions: {len(survey_data.get('questions', []))}\n")
        for q in survey_data.get("questions", []):
            parts.append(f"- [{q['id']}] ({q['type']}) {q['text']}")
        parts.append("")

    parts.append(f"# RAW SURVEY RESPONSES ({len(valid)} respondents)\n")
    for r in valid:
        entry = f"## [{r.get('archetype_label', '?')}] {r.get('persona_id', '?')}\n"
        for answer in r.get("answers", []):
            qid = answer.get("question_id", "?")
            val = answer.get("value", "")
            if isinstance(val, list):
                val = ", ".join(str(v) for v in val)
            entry += f"- **{qid}**: {val}\n"
        parts.append(entry)

    if marketing_report:
        parts.append("# MARKETING RESEARCHER'S REPORT\n")
        parts.append(marketing_report.strip())
        parts.append("")

    parts.append(
        "\n---\n"
        "You commissioned this research. Now analyze all the data and the Marketing "
        "Researcher's report. Produce your strategic analysis with go/no-go verdict."
    )

    return "\n".join(parts)


async def generate_research_brief(
    feature_text: str,
    run_dir: Path,
    analyst_id: str = "product_owner",
    backend: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    agentic: bool = True,
    max_steps: int = 5,
) -> Path:
    """PO Turn 1: Read feature, write research_brief.md for Marketing."""
    analyst = get_analyst(analyst_id)
    defaults = get_analyst_defaults()

    resolved_backend = backend or defaults.get("backend", "gemini")
    resolved_model = model or defaults.get("model", GEMINI_DEFAULT_MODEL)
    resolved_temperature = (
        temperature if temperature is not None else defaults.get("temperature", 0.4)
    )
    resolved_max_tokens = (
        max_tokens if max_tokens is not None else defaults.get("max_tokens", 4096)
    )

    skills = analyst.get("skills", [])
    use_agentic = agentic and bool(skills) and resolved_backend == "bedrock"
    system_prompt = _build_brief_system_prompt(analyst, include_tools=use_agentic)

    user_prompt = (
        "# FEATURE TO RESEARCH\n\n"
        f"{feature_text.strip()}\n\n"
        "---\n\n"
        "Write a research brief for your Marketing Researcher. "
        "Tell them exactly what to investigate and what questions the survey should answer."
    )

    logger.info(
        f"[{analyst['label']}] Writing research brief | "
        f"mode={'agentic' if use_agentic else 'single-shot'} | model={resolved_model}"
    )

    if use_agentic:
        brief_text = await _call_bedrock_agentic(
            system_prompt,
            user_prompt,
            resolved_model,
            resolved_temperature,
            resolved_max_tokens,
            skills,
            max_steps,
            f"{analyst['label']} (brief)",
        )
    elif resolved_backend == "bedrock":
        brief_text = await _call_bedrock(
            system_prompt,
            user_prompt,
            resolved_model,
            resolved_temperature,
            resolved_max_tokens,
        )
    elif resolved_backend == "gemini":
        brief_text = await _call_gemini(
            system_prompt,
            user_prompt,
            resolved_model,
            resolved_temperature,
            resolved_max_tokens,
        )
    else:
        brief_text = None

    if not brief_text:
        raise RuntimeError(f"{analyst['label']} research brief LLM call failed")

    header = (
        f"# Research Brief\n\n"
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"**From:** {analyst['label']}\n"
        f"**To:** Marketing Researcher\n"
        f"**Model:** {resolved_model}\n\n---\n\n"
    )

    brief_path = run_dir / "research_brief.md"
    brief_path.write_text(header + brief_text, encoding="utf-8")
    logger.info(f"[{analyst['label']}] Research brief saved -> {brief_path}")

    return brief_path


GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
GEMINI_DEFAULT_MODEL = "gemini-3-flash-preview"

BEDROCK_REGION = os.environ.get("AWS_DEFAULT_REGION", "ap-southeast-2")

try:
    from botocore.config import Config as BotoConfig

    BEDROCK_TIMEOUT = BotoConfig(read_timeout=600, retries={"max_attempts": 2})
except ImportError:
    BotoConfig = None  # type: ignore[assignment,misc]
    BEDROCK_TIMEOUT = None


def _get_bedrock_client():
    if not hasattr(_get_bedrock_client, "_client"):
        _get_bedrock_client._client = boto3.client(
            "bedrock-runtime", region_name=BEDROCK_REGION, config=BEDROCK_TIMEOUT
        )
    return _get_bedrock_client._client


async def _call_gemini(
    system_prompt: str,
    user_prompt: str,
    model: str,
    temperature: float,
    max_tokens: int,
) -> str | None:
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        logger.error("GEMINI_API_KEY not set")
        return None

    gemini_model = model if "/" not in model else model.split("/")[-1]
    url = GEMINI_API_URL.format(model=gemini_model) + f"?key={api_key}"

    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        },
    }

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(180.0, connect=10.0), verify=False
    ) as client:
        for attempt in range(3):
            try:
                resp = await client.post(url, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    parts = data["candidates"][0]["content"]["parts"]
                    return next(
                        (p["text"] for p in parts if not p.get("thought")),
                        parts[-1].get("text", ""),
                    )
                elif resp.status_code == 429:
                    wait = 5 * (attempt + 1)
                    logger.warning(f"Rate limited (429). Waiting {wait}s...")
                    await asyncio.sleep(wait)
                else:
                    logger.error(f"Gemini error {resp.status_code}: {resp.text[:300]}")
            except Exception as e:
                logger.error(f"Connection error (attempt {attempt + 1}): {e}")
                await asyncio.sleep(3)
    return None


async def _call_bedrock(
    system_prompt: str,
    user_prompt: str,
    model: str,
    temperature: float,
    max_tokens: int,
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
                logger.warning(f"Bedrock throttled. Waiting {wait}s...")
                await asyncio.sleep(wait)
            else:
                logger.error(f"Bedrock error (attempt {attempt + 1}): {e}")
                await asyncio.sleep(3)
    return None


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
    analyst_label: str = "Analyst",
) -> str | None:
    """ReAct loop on Bedrock Converse with tool calling for analyst agents."""
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
                wait = 5 * (step)
                logger.warning(
                    f"[{analyst_label}] Bedrock throttled step {step}. Waiting {wait}s..."
                )
                await asyncio.sleep(wait)
                continue
            else:
                err_str = str(e)
                logger.error(f"[{analyst_label}] Bedrock error step {step}: {e}")

                if (
                    "add_generation_prompt" in err_str
                    or "last message is from the assistant" in err_str
                ):
                    logger.warning(
                        f"[{analyst_label}] Detected Mistral message format bug — recovering by forcing user turn"
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
                    "toolUse.name" in err_str
                    and "failed to satisfy constraint" in err_str
                ):
                    logger.warning(
                        f"[{analyst_label}] Malformed tool name in history — scrubbing and retrying"
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
                f"[{analyst_label}] Step {step}: tool_use ({len(tool_blocks)} call(s)) "
                f"[{model}] (total: {total_tool_calls})"
            )
            continue

        if stop_reason == "end_turn":
            text_parts = [c["text"] for c in assistant_msg["content"] if c.get("text")]
            raw_text = "\n".join(text_parts)
            logger.info(
                f"[{analyst_label}] Step {step}: end_turn | "
                f"tools={total_tool_calls} [{model}]"
            )
            return raw_text

    logger.warning(f"[{analyst_label}] Max steps reached, forcing final answer")
    messages.append(
        {
            "role": "user",
            "content": [{"text": "Please produce your final markdown report now."}],
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
        logger.error(f"[{analyst_label}] Final forced call failed: {e}")
    return None


async def run_po_analysis(
    run_dir: Path,
    analyst_id: str = "product_owner",
    backend: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    dry_run: bool = False,
    agentic: bool = True,
    max_steps: int = 5,
) -> Path:
    """Run an analyst persona agent on an existing simulation run. Returns the report path."""
    analyst = get_analyst(analyst_id)
    defaults = get_analyst_defaults()

    resolved_backend = backend or defaults.get("backend", "gemini")
    resolved_model = model or defaults.get("model", GEMINI_DEFAULT_MODEL)
    resolved_temperature = (
        temperature if temperature is not None else defaults.get("temperature", 0.4)
    )
    resolved_max_tokens = (
        max_tokens if max_tokens is not None else defaults.get("max_tokens", 4096)
    )

    skills = analyst.get("skills", [])
    use_agentic = agentic and bool(skills) and resolved_backend == "bedrock"
    system_prompt = build_system_prompt(analyst, include_tools=use_agentic)

    survey_responses_path = run_dir / "survey_responses.json"
    raw_path = run_dir / "raw_responses.json"
    is_survey_mode = survey_responses_path.exists()

    if is_survey_mode:
        responses = json.loads(survey_responses_path.read_text(encoding="utf-8"))
    elif raw_path.exists():
        responses = json.loads(raw_path.read_text(encoding="utf-8"))
    else:
        raise FileNotFoundError(
            f"No survey_responses.json or raw_responses.json in {run_dir}"
        )

    feature_text = ""
    feature_path = run_dir / "feature.txt"
    if feature_path.exists():
        feature_text = feature_path.read_text(encoding="utf-8")

    valid = [r for r in responses if not r.get("error")]

    if is_survey_mode:
        survey_data: dict[str, Any] = {}
        survey_path = run_dir / "survey.json"
        if survey_path.exists():
            survey_data = json.loads(survey_path.read_text(encoding="utf-8"))

        marketing_report: str | None = None
        mkt_report_path = run_dir / "marketing_report.md"
        if mkt_report_path.exists():
            marketing_report = mkt_report_path.read_text(encoding="utf-8")

        research_brief: str | None = None
        brief_path = run_dir / "research_brief.md"
        if brief_path.exists():
            research_brief = brief_path.read_text(encoding="utf-8")

        logger.info(
            f"[{analyst['label']}] Analyzing {len(valid)} survey responses | "
            f"survey mode | marketing_report={'yes' if marketing_report else 'no'}"
        )
    else:
        stats: dict[str, Any] = {}
        stats_path = run_dir / "stats.json"
        if stats_path.exists():
            stats = json.loads(stats_path.read_text(encoding="utf-8"))
        else:
            from aggregator import compute_stats

            stats = compute_stats(responses)

        feedback_report: str | None = None
        report_path = run_dir / "feedback_report.md"
        if report_path.exists():
            feedback_report = report_path.read_text(encoding="utf-8")

        logger.info(
            f"[{analyst['label']}] Analyzing {len(valid)} responses | "
            f"avg sentiment: {stats.get('avg_sentiment', '?')} | "
            f"would-use: {stats.get('would_use_pct', '?')}%"
        )

    analysis_text: str | None
    if dry_run:
        logger.info("DRY RUN -- using template analysis")
        analysis_text = DRY_RUN_REPORT
    else:
        if is_survey_mode:
            user_prompt = _build_survey_user_prompt(
                feature_text,
                survey_data,
                responses,
                marketing_report,
                research_brief,
            )
        else:
            user_prompt = _build_user_prompt(
                feature_text, stats, responses, feedback_report
            )

        if use_agentic:
            logger.info(
                f"Calling Bedrock AGENTIC ({resolved_model}) as {analyst['label']} | "
                f"skills={skills} | max_steps={max_steps}"
            )
            analysis_text = await _call_bedrock_agentic(
                system_prompt,
                user_prompt,
                resolved_model,
                resolved_temperature,
                resolved_max_tokens,
                skills,
                max_steps,
                analyst["label"],
            )
        elif resolved_backend == "gemini":
            logger.info(f"Calling Gemini ({resolved_model}) as {analyst['label']}...")
            analysis_text = await _call_gemini(
                system_prompt,
                user_prompt,
                resolved_model,
                resolved_temperature,
                resolved_max_tokens,
            )
        elif resolved_backend == "bedrock":
            logger.info(f"Calling Bedrock ({resolved_model}) as {analyst['label']}...")
            analysis_text = await _call_bedrock(
                system_prompt,
                user_prompt,
                resolved_model,
                resolved_temperature,
                resolved_max_tokens,
            )
        else:
            logger.error(f"Unsupported backend: {resolved_backend}")
            analysis_text = None

        if not analysis_text:
            logger.error(f"{analyst['label']} LLM call failed -- no analysis produced")
            analysis_text = f"*{analyst['label']} analysis failed. Re-run with --dry-run to see template output.*"

    mode_label = "dry-run" if dry_run else ("agentic" if use_agentic else "single-shot")
    skills_label = ", ".join(skills) if skills and use_agentic else "none"
    data_mode = "survey" if is_survey_mode else "feedback"

    if is_survey_mode:
        source_line = f"**Source data:** {len(valid)} survey responses"
    else:
        avg_sent = stats.get("avg_sentiment", "?")
        would_use = stats.get("would_use_pct", "?")
        avg_sent_str = (
            f"{avg_sent:.1f}" if isinstance(avg_sent, (int, float)) else str(avg_sent)
        )
        would_use_str = (
            f"{would_use:.0f}"
            if isinstance(would_use, (int, float))
            else str(would_use)
        )
        source_line = (
            f"**Source data:** {len(valid)} customer responses "
            f"(avg sentiment {avg_sent_str}/5, {would_use_str}% would-use)"
        )

    header = (
        f"# {analyst['label']} Analysis\n\n"
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"**Persona:** {analyst['label']}\n"
        f"**Backend:** {'dry-run' if dry_run else resolved_backend}\n"
        f"**Model:** {'template' if dry_run else resolved_model}\n"
        f"**Mode:** {mode_label}\n"
        f"**Skills:** {skills_label}\n"
        f"**Data mode:** {data_mode}\n"
        f"{source_line}\n\n"
        f"---\n\n"
    )

    full_report = header + analysis_text
    output_path = run_dir / "po_analysis.md"
    output_path.write_text(full_report, encoding="utf-8")
    logger.info(f"{analyst['label']} analysis saved -> {output_path}")

    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="Analyst Agent (loads persona from analysts.json)"
    )
    parser.add_argument(
        "--run-dir", type=str, required=True, help="Path to simulation run directory"
    )
    parser.add_argument(
        "--analyst",
        type=str,
        default="product_owner",
        help="Analyst persona ID from analysts.json (default: product_owner)",
    )
    parser.add_argument(
        "--backend",
        type=str,
        default=None,
        choices=["gemini", "bedrock"],
        help="LLM backend (default: from analysts.json defaults)",
    )
    parser.add_argument("--model", type=str, default=None, help="LLM model override")
    parser.add_argument(
        "--temperature",
        type=float,
        default=None,
        help="LLM temperature (default: from analysts.json)",
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=None,
        help="Max output tokens (default: from analysts.json)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Use template output without calling LLM"
    )
    parser.add_argument(
        "--agentic",
        action="store_true",
        default=True,
        help="Enable agentic mode with tool calling (default: True)",
    )
    parser.add_argument(
        "--no-agentic",
        dest="agentic",
        action="store_false",
        help="Disable agentic mode, run single-shot",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=5,
        help="Max ReAct loop steps in agentic mode (default: 5)",
    )
    parser.add_argument(
        "--region", type=str, default=None, help="AWS region for bedrock backend"
    )
    args = parser.parse_args()

    if args.region:
        os.environ["AWS_DEFAULT_REGION"] = args.region

    run_dir = Path(args.run_dir)
    if not run_dir.exists():
        logger.error(f"Run directory not found: {run_dir}")
        sys.exit(1)

    output_path = asyncio.run(
        run_po_analysis(
            run_dir=run_dir,
            analyst_id=args.analyst,
            backend=args.backend,
            model=args.model,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            dry_run=args.dry_run,
            agentic=args.agentic,
            max_steps=args.max_steps,
        )
    )

    print(f"\nAnalysis complete -> {output_path}")


if __name__ == "__main__":
    main()
