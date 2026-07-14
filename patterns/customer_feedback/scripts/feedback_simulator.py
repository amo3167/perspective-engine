"""
Customer Feedback Simulator — Async batched LLM orchestrator.

Generates N synthetic customer personas, broadcasts a feature announcement to
each, and collects structured JSON feedback. Results are stored in Redis
(SharedMemory) and written to a local JSON file for the aggregator.

Usage:
    python feedback_simulator.py --feature path/to/feature.md --count 10
    python feedback_simulator.py --feature path/to/feature.md --count 10 --batch-size 5
    python feedback_simulator.py --feature path/to/feature.md --count 10 --dry-run
"""

import sys
import os
import json
import asyncio
import logging
import random
import argparse
from datetime import datetime
from pathlib import Path
from typing import Any

from pe_layout import ensure_sys_path, load_dotenv_layers

ensure_sys_path()
load_dotenv_layers()

LITELLM_API_BASE = None
LITELLM_API_KEY = None
SharedMemory = None

try:
    import httpx
    from engine.shared_memory import SharedMemory as _SM

    SharedMemory = _SM
    LITELLM_API_BASE = os.getenv("LITELLM_API_BASE")
    LITELLM_API_KEY = os.getenv("LITELLM_API_KEY") or os.getenv("GEMINI_API_KEY")
except ImportError:
    try:
        import httpx
        from agent_boxes.shared_memory import SharedMemory as _SM
        from agent_gateway.config import LITELLM_API_BASE as _BASE, LITELLM_API_KEY as _KEY

        SharedMemory = _SM
        LITELLM_API_BASE = _BASE
        LITELLM_API_KEY = _KEY
    except ImportError:
        pass

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment]

try:
    import boto3
except ImportError:
    boto3 = None  # type: ignore[assignment]

from archetype_generator import generate_personas, load_profiles

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [feedback_sim] - %(levelname)s - %(message)s",
)
logger = logging.getLogger("feedback_simulator")

SKILL_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_BASE = SKILL_ROOT / "output"

_broadcast_client: "httpx.AsyncClient | None" = None


async def _broadcast(url: str | None, event: dict) -> None:
    """Fire-and-forget POST to the monitor broadcast endpoint."""
    global _broadcast_client
    if not url or httpx is None:
        return
    try:
        if _broadcast_client is None:
            _broadcast_client = httpx.AsyncClient(timeout=5)
        await _broadcast_client.post(url, json={"type": "feedback_update", **event})
    except Exception:
        pass

RESPONSE_SCHEMA_INSTRUCTIONS = """\
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


def build_system_prompt(persona: dict[str, Any]) -> str:
    context_lines: list[str] = []
    if persona.get("quirk"):
        context_lines.append(f"You are a {persona['quirk']}.")
    if persona.get("region"):
        context_lines.append(f"You are based in {persona['region']}.")
    if persona.get("tenure"):
        context_lines.append(f"Your account tenure: {persona['tenure']}.")
    if persona.get("plan"):
        context_lines.append(f"Your subscription: {persona['plan']}.")
    if persona.get("use_case"):
        context_lines.append(f"Primary use case: {persona['use_case']}.")
    if persona.get("emotional_state"):
        context_lines.append(f"Current mood: {persona['emotional_state']}.")
    context_block = "\n".join(context_lines)
    if context_block:
        context_block = f"\n{context_block}"

    return (
        f"You are a simulated customer providing feedback on a new product feature.\n"
        f"Your persona: {persona['soul']}\n"
        f"Your response style: {persona['response_style']}\n"
        f"Your age: {persona['age']} | Tech level: {persona['tech_level']} | "
        f"Patience (1-10): {persona['patience']} | Language style: {persona['language_style']}\n"
        f"Your general satisfaction bias: {persona['satisfaction_bias']}"
        f"{context_block}\n\n"
        f"Stay fully in character. Do NOT break character or mention that you are an AI.\n"
        f"Provide authentic, varied feedback as this specific person would.\n\n"
        f"{RESPONSE_SCHEMA_INSTRUCTIONS}"
    )


def build_user_prompt(feature_text: str) -> str:
    return (
        f"--- FEATURE ANNOUNCEMENT ---\n\n"
        f"{feature_text}\n\n"
        f"--- END ANNOUNCEMENT ---\n\n"
        f"Please provide your honest feedback on this new feature."
    )


def parse_llm_response(raw: str) -> dict[str, Any] | None:
    """Best-effort JSON extraction from LLM response.

    Handles markdown fences, <think>...</think> blocks (MiniMax M2.7 / DeepSeek),
    and raw JSON with surrounding text.
    """
    import re

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
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass
    return None


DRY_RUN_FEEDBACK: dict[str, dict[str, Any]] = {
    "power_user": {
        "sentiment_range": (2, 4),
        "would_use_prob": 0.7,
        "feedback_templates": [
            "The API access and export features are solid, but I need WebSocket streaming for real-time data, not polling every 30 seconds. Also, where are the keyboard shortcuts?",
            "Good foundation but the 30-second update interval is unacceptable for active trading. Need sub-second latency. The CSV export better support custom date ranges.",
            "Sharpe ratio and profit factor are a start, but I need Sortino, Calmar, and custom risk metrics. Let me define my own calculated fields via an API.",
        ],
        "concerns_pool": ["30-second update latency too slow", "no API documentation mentioned", "no keyboard shortcuts", "no custom metric definitions"],
        "requests_pool": ["WebSocket real-time streaming", "API endpoint for programmatic access", "custom calculated fields", "dark mode"],
    },
    "casual_user": {
        "sentiment_range": (3, 5),
        "would_use_prob": 0.8,
        "feedback_templates": [
            "Looks nice! I like being able to see my P&L easily. The mobile thing is great too.",
            "Cool, I'd use the chart thing. Not sure what Sharpe ratio means but the rest looks useful.",
            "Sounds good. As long as it's easy to find and doesn't slow things down.",
            "Nice update. I mostly just want to see if I'm making money or not lol.",
        ],
        "concerns_pool": ["might be confusing", "hope it doesn't slow down the app", "too many features I won't use"],
        "requests_pool": ["simple mode/view", "push notifications for big changes", "tutorial or walkthrough"],
    },
    "privacy_skeptic": {
        "sentiment_range": (2, 4),
        "would_use_prob": 0.4,
        "feedback_templates": [
            "Before I use this: where is the portfolio data stored? Is it encrypted at rest? Who else can see my trading performance?",
            "The export to PDF is fine, but I want to know if my equity curve data is being shared with any third parties or used for analytics.",
            "I'd consider using this if there's a clear data retention policy. Can I delete my dashboard data independently?",
        ],
        "concerns_pool": ["data storage location unclear", "third-party data sharing", "no mention of encryption", "data retention policy needed"],
        "requests_pool": ["data export with full deletion option", "privacy policy specific to dashboard", "opt-out of analytics tracking", "local-only mode"],
    },
    "change_resistant": {
        "sentiment_range": (1, 3),
        "would_use_prob": 0.3,
        "feedback_templates": [
            "Why are you replacing the current P&L page? It worked fine. Now I have to learn a whole new interface.",
            "I don't need fancy charts. The old summary was simple and fast. This looks overcomplicated.",
            "Great, another update that moves everything around. I just got used to where things were.",
        ],
        "concerns_pool": ["replacing a working page", "unnecessary complexity", "learning curve", "things moved around again"],
        "requests_pool": ["keep the old simple view as an option", "don't force the change", "migration guide from old to new"],
    },
    "early_adopter": {
        "sentiment_range": (4, 5),
        "would_use_prob": 0.9,
        "feedback_templates": [
            "Love this! The strategy comparison overlay is exactly what I've been wanting. Suggestion: add a benchmark comparison (e.g., vs S&P 500) too.",
            "Finally! This is a huge upgrade. The risk metrics panel is great. Would be even better with a correlation matrix between strategies.",
            "Super excited to try this. The mobile-responsive design is key for me. One idea: add shareable report links so I can discuss with my trading group.",
        ],
        "concerns_pool": ["hope it ships soon", "might need polish after launch"],
        "requests_pool": ["benchmark comparison overlay", "shareable report links", "correlation matrix", "historical backtest overlay", "alerts via Telegram"],
    },
    "budget_conscious": {
        "sentiment_range": (2, 4),
        "would_use_prob": 0.5,
        "feedback_templates": [
            "Is this included in the free plan? Because if it's a premium upsell, I'll pass.",
            "Looks nice but TradingView gives me most of this for free. What's the added value?",
        ],
        "concerns_pool": ["hidden costs", "feature gating behind premium", "competitors offer similar for free"],
        "requests_pool": ["keep core dashboard on free tier", "transparent pricing for premium features"],
    },
    "accessibility_advocate": {
        "sentiment_range": (2, 4),
        "would_use_prob": 0.5,
        "feedback_templates": [
            "The equity curve chart needs ARIA labels and a data table alternative. Screen readers can't parse SVG charts.",
            "Keyboard navigation for the strategy comparison overlay? Tab order? Focus indicators?",
        ],
        "concerns_pool": ["charts inaccessible to screen readers", "no mention of keyboard navigation", "color-only indicators"],
        "requests_pool": ["ARIA labels on all charts", "high contrast mode", "data table alternative for every chart"],
    },
    "enterprise_admin": {
        "sentiment_range": (3, 4),
        "would_use_prob": 0.7,
        "feedback_templates": [
            "Can I restrict dashboard access per role? Our compliance team won't approve if all users see everything.",
            "Looks useful but I need to evaluate training overhead for 200+ users before rolling this out.",
        ],
        "concerns_pool": ["role-based access control", "training overhead for team", "audit logging"],
        "requests_pool": ["RBAC for dashboard widgets", "bulk export for compliance", "admin-controlled default views"],
    },
    "newcomer": {
        "sentiment_range": (3, 4),
        "would_use_prob": 0.6,
        "feedback_templates": [
            "I'm still learning the basics. This looks cool but I'd need a tutorial first.",
            "Wait, what's a drawdown? I don't even know what half these metrics mean yet.",
        ],
        "concerns_pool": ["too advanced for beginners", "no tutorial or walkthrough", "overwhelming"],
        "requests_pool": ["beginner mode with tooltips", "guided tour for new users", "glossary of terms"],
    },
    "data_driven": {
        "sentiment_range": (3, 4),
        "would_use_prob": 0.7,
        "feedback_templates": [
            "CSV export is good, but I need JSON/Parquet and a REST API to pipe into my Python pipeline.",
            "The chart is pretty, but what's the underlying data granularity? Minute-level? Tick-level?",
        ],
        "concerns_pool": ["limited export formats", "no API for programmatic access", "unclear data granularity"],
        "requests_pool": ["REST API for all metrics", "JSON/Parquet export", "webhook for real-time data push"],
    },
    "social_sharer": {
        "sentiment_range": (4, 5),
        "would_use_prob": 0.8,
        "feedback_templates": [
            "Can I share a screenshot of my equity curve? This would look amazing on Twitter!",
            "Love it! If there's a shareable link with a preview card, I'll post it to my Discord server immediately.",
        ],
        "concerns_pool": ["screenshots might expose private data", "no social sharing built in"],
        "requests_pool": ["one-click share with privacy filter", "OG preview cards for links", "achievement badges"],
    },
}


def generate_dry_run_response(persona: dict[str, Any]) -> dict[str, Any]:
    """Generate a plausible mock response based on the persona's archetype."""
    arch = persona["archetype_id"]
    template = DRY_RUN_FEEDBACK.get(arch, DRY_RUN_FEEDBACK["casual_user"])

    sentiment = random.randint(*template["sentiment_range"])
    would_use = random.random() < template["would_use_prob"]
    feedback = random.choice(template["feedback_templates"])
    num_concerns = random.randint(0, min(2, len(template["concerns_pool"])))
    num_requests = random.randint(0, min(2, len(template["requests_pool"])))
    concerns = random.sample(template["concerns_pool"], num_concerns)
    requests = random.sample(template["requests_pool"], num_requests)

    return {
        "persona_id": persona["persona_id"],
        "archetype_id": persona["archetype_id"],
        "archetype_label": persona["archetype_label"],
        "sentiment": sentiment,
        "would_use": would_use,
        "feedback": feedback,
        "concerns": concerns,
        "feature_requests": requests,
    }


GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_DEFAULT_MODEL = "gemini-3-flash-preview"


def _error_response(persona: dict[str, Any]) -> dict[str, Any]:
    return {
        "persona_id": persona["persona_id"],
        "archetype_id": persona["archetype_id"],
        "archetype_label": persona["archetype_label"],
        "sentiment": 3,
        "would_use": False,
        "feedback": "[LLM call failed after 3 attempts]",
        "concerns": [],
        "feature_requests": [],
        "error": True,
    }


def _tag_response(parsed: dict[str, Any], persona: dict[str, Any]) -> dict[str, Any]:
    parsed["persona_id"] = persona["persona_id"]
    parsed["archetype_id"] = persona["archetype_id"]
    parsed["archetype_label"] = persona["archetype_label"]
    return parsed


async def call_gemini_direct(
    client: Any,
    persona: dict[str, Any],
    feature_text: str,
    model: str,
    temperature: float,
    max_tokens: int,
) -> dict[str, Any]:
    """Call Gemini REST API directly (no LiteLLM proxy needed)."""
    gemini_model = model if "/" not in model else model.split("/")[-1]
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        logger.error("GEMINI_API_KEY not set")
        return _error_response(persona)

    system_prompt = build_system_prompt(persona)
    user_prompt = build_user_prompt(feature_text)
    url = GEMINI_API_URL.format(model=gemini_model) + f"?key={api_key}"

    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }

    for attempt in range(3):
        try:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                parts = data["candidates"][0]["content"]["parts"]
                raw = next((p["text"] for p in parts if not p.get("thought")), parts[-1].get("text", ""))
                parsed = parse_llm_response(raw)
                if parsed and "sentiment" in parsed:
                    return _tag_response(parsed, persona)
                logger.warning(
                    f"[{persona['persona_id']}] Attempt {attempt + 1}: invalid JSON, retrying..."
                )
            elif resp.status_code == 429:
                wait = 5 * (attempt + 1)
                logger.warning(f"[{persona['persona_id']}] Rate limited (429). Waiting {wait}s...")
                await asyncio.sleep(wait)
            else:
                logger.error(f"[{persona['persona_id']}] Gemini error {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            logger.error(f"[{persona['persona_id']}] Connection error (attempt {attempt + 1}): {e}")
            await asyncio.sleep(3)

    return _error_response(persona)


MINIMAX_API_BASE = "https://api.minimaxi.com/v1"
MINIMAX_MODEL = "MiniMax-M2.7"


async def call_minimax_direct(
    client: Any,
    persona: dict[str, Any],
    feature_text: str,
    model: str,
    temperature: float,
    max_tokens: int,
) -> dict[str, Any]:
    """Call MiniMax M2.7 via OpenAI-compatible chat completions endpoint."""
    api_key = (os.environ.get("MINIMAX_CODING_API_KEY") or os.environ.get("MINIMAX_API_KEY", "")).strip('" ')
    if not api_key:
        logger.error("MINIMAX_CODING_API_KEY / MINIMAX_API_KEY not set")
        return _error_response(persona)

    system_prompt = build_system_prompt(persona)
    user_prompt = build_user_prompt(feature_text)
    url = f"{MINIMAX_API_BASE}/chat/completions"

    payload = {
        "model": model if model != GEMINI_DEFAULT_MODEL else MINIMAX_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": max_tokens * 4,
        "temperature": temperature,
    }
    headers = {"Authorization": f"Bearer {api_key}"}

    max_attempts = 6
    for attempt in range(max_attempts):
        try:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code == 200:
                result = resp.json()
                raw = result["choices"][0]["message"]["content"]
                parsed = parse_llm_response(raw)
                if parsed and "sentiment" in parsed:
                    return _tag_response(parsed, persona)
                logger.warning(
                    f"[{persona['persona_id']}] Attempt {attempt + 1}: invalid JSON, retrying..."
                )
            elif resp.status_code in (429, 529):
                wait = 3 * (attempt + 1)
                logger.warning(
                    f"[{persona['persona_id']}] Overloaded ({resp.status_code}). "
                    f"Waiting {wait}s... (attempt {attempt + 1}/{max_attempts})"
                )
                await asyncio.sleep(wait)
            else:
                logger.error(f"[{persona['persona_id']}] MiniMax error {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            logger.error(f"[{persona['persona_id']}] Connection error (attempt {attempt + 1}): {e}")
            await asyncio.sleep(3)

    return _error_response(persona)


async def call_litellm_proxy(
    client: Any,
    persona: dict[str, Any],
    feature_text: str,
    model: str,
    temperature: float,
    max_tokens: int,
) -> dict[str, Any]:
    """Call LiteLLM proxy (OpenAI-compatible) for a single persona."""
    system_prompt = build_system_prompt(persona)
    user_prompt = build_user_prompt(feature_text)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    for attempt in range(3):
        try:
            resp = await client.post(
                f"{LITELLM_API_BASE}/chat/completions",
                headers={"Authorization": f"Bearer {LITELLM_API_KEY}"},
                json={
                    "model": model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                },
            )
            if resp.status_code == 200:
                result = resp.json()
                raw = result["choices"][0]["message"]["content"]
                parsed = parse_llm_response(raw)
                if parsed and "sentiment" in parsed:
                    return _tag_response(parsed, persona)
                logger.warning(
                    f"[{persona['persona_id']}] Attempt {attempt + 1}: invalid JSON response, retrying..."
                )
            elif resp.status_code == 429:
                wait = 5 * (attempt + 1)
                logger.warning(f"[{persona['persona_id']}] Rate limited (429). Waiting {wait}s...")
                await asyncio.sleep(wait)
            else:
                logger.error(f"[{persona['persona_id']}] LLM error {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            logger.error(f"[{persona['persona_id']}] Connection error (attempt {attempt + 1}): {e}")
            await asyncio.sleep(3)

    return _error_response(persona)


BEDROCK_REGION = os.environ.get("AWS_DEFAULT_REGION", "ap-southeast-2")


def _get_bedrock_client():
    """Lazy singleton for bedrock-runtime client (thread-safe enough for asyncio)."""
    if not hasattr(_get_bedrock_client, "_client"):
        _get_bedrock_client._client = boto3.client(
            "bedrock-runtime", region_name=BEDROCK_REGION
        )
    return _get_bedrock_client._client


async def call_bedrock_converse(
    client: Any,
    persona: dict[str, Any],
    feature_text: str,
    model: str,
    temperature: float,
    max_tokens: int,
) -> dict[str, Any]:
    """Call AWS Bedrock Converse API. `client` is ignored (uses boto3)."""
    if boto3 is None:
        logger.error("boto3 not installed")
        return _error_response(persona)

    bedrock = _get_bedrock_client()
    system_prompt = build_system_prompt(persona)
    user_prompt = build_user_prompt(feature_text)

    bedrock_model = persona.get("_bedrock_model", model)

    for attempt in range(4):
        try:
            resp = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: bedrock.converse(
                    modelId=bedrock_model,
                    system=[{"text": system_prompt}],
                    messages=[{"role": "user", "content": [{"text": user_prompt}]}],
                    inferenceConfig={
                        "maxTokens": max_tokens * 4,
                        "temperature": temperature,
                    },
                ),
            )
            raw = resp["output"]["message"]["content"][0]["text"]
            latency = resp.get("metrics", {}).get("latencyMs", "?")
            parsed = parse_llm_response(raw)
            if parsed and "sentiment" in parsed:
                parsed["_model"] = bedrock_model
                parsed["_latency_ms"] = latency
                return _tag_response(parsed, persona)
            logger.warning(
                f"[{persona['persona_id']}] Attempt {attempt + 1}: invalid JSON from {bedrock_model}, retrying..."
            )
        except bedrock.exceptions.ThrottlingException:
            wait = 5 * (attempt + 1)
            logger.warning(
                f"[{persona['persona_id']}] Bedrock throttled. Waiting {wait}s... (attempt {attempt + 1}/4)"
            )
            await asyncio.sleep(wait)
        except Exception as e:
            logger.error(f"[{persona['persona_id']}] Bedrock error (attempt {attempt + 1}): {e}")
            await asyncio.sleep(3)

    return _error_response(persona)


def _log_handoff(from_agent: str, to_agent: str, artifact: Path, run_dir: Path) -> None:
    entry = {
        "timestamp": datetime.now().isoformat(),
        "from": from_agent,
        "to": to_agent,
        "artifact": artifact.name,
        "artifact_size_bytes": artifact.stat().st_size if artifact.exists() else 0,
    }
    trace_path = run_dir / "pipeline_trace.json"
    trace: list[dict[str, Any]] = []
    if trace_path.exists():
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
    trace.append(entry)
    trace_path.write_text(json.dumps(trace, indent=2), encoding="utf-8")
    logger.info(f"  HANDOFF: {from_agent} -> {to_agent} via {artifact.name}")


async def _run_survey_pipeline(
    feature_text: str,
    run_dir: Path,
    count: int,
    batch_size: int,
    seed: int | None,
    model: str | None,
    models: str | None,
    backend: str,
    agentic: bool,
    max_steps: int,
    dry_run: bool,
    broadcast_url: str | None = None,
) -> None:
    """5-step research pipeline: PO brief -> Marketing survey -> customers -> compile -> PO analysis."""
    pipeline_meta: dict[str, Any] = {
        "type": "research_pipeline",
        "timestamp": datetime.now().isoformat(),
        "feature_length": len(feature_text),
        "count": count,
        "backend": backend,
        "model": model,
        "agentic": agentic,
        "dry_run": dry_run,
        "steps": [],
    }

    import time as _time
    _pipeline_t0 = _time.monotonic()

    logger.info("=" * 70)
    logger.info("RESEARCH PIPELINE STARTED")
    logger.info(f"  Run dir: {run_dir}")
    logger.info(f"  Respondents: {count} | Backend: {backend} | Agentic: {agentic}")
    logger.info("=" * 70)

    await _broadcast(broadcast_url, {
        "feedback_type": "pipeline_start",
        "run_id": run_dir.name,
        "mode": "survey",
        "count": count,
    })

    # Step 1: PO writes research brief
    logger.info("")
    logger.info("STEP 1/5: Product Owner writes research brief")
    logger.info("-" * 50)
    _step_t0 = _time.monotonic()
    await _broadcast(broadcast_url, {
        "feedback_type": "step_start", "run_id": run_dir.name,
        "step": 1, "agent": "product_owner",
        "message": "Product Owner is writing the research brief...",
    })

    from po_analyst import generate_research_brief

    if dry_run:
        brief_text = (
            "# Research Brief\n\n"
            "**From:** Product Owner\n**To:** Marketing Researcher\n\n"
            "## Feature Overview\nNew portfolio performance dashboard.\n\n"
            "## Research Objectives\n- Validate adoption likelihood across segments\n"
            "- Identify top concerns and blockers\n\n"
            "## Hypotheses to Validate\n- Power users will want API access\n"
            "- Newcomers will find it overwhelming\n"
        )
        brief_path = run_dir / "research_brief.md"
        brief_path.write_text(brief_text, encoding="utf-8")
        logger.info("[DRY RUN] Using template brief")
    else:
        brief_path = await generate_research_brief(
            feature_text, run_dir,
            analyst_id="product_owner",
            backend=backend, model=model,
            agentic=agentic, max_steps=max_steps,
        )

    pipeline_meta["steps"].append({"step": 1, "agent": "product_owner", "output": "research_brief.md"})
    _log_handoff("product_owner", "marketing_researcher", brief_path, run_dir)
    await _broadcast(broadcast_url, {
        "feedback_type": "step_complete", "run_id": run_dir.name,
        "step": 1, "agent": "product_owner", "artifact": "research_brief.md",
        "elapsed_ms": int((_time.monotonic() - _step_t0) * 1000),
    })

    # Step 2: Marketing designs survey
    logger.info("")
    logger.info("STEP 2/5: Marketing Researcher designs survey")
    logger.info("-" * 50)
    _step_t0 = _time.monotonic()
    await _broadcast(broadcast_url, {
        "feedback_type": "step_start", "run_id": run_dir.name,
        "step": 2, "agent": "marketing_researcher",
        "message": "Marketing Researcher is designing the survey...",
    })

    from marketing_agent import design_survey

    if dry_run:
        survey_data = {
            "title": "Portfolio Dashboard Feedback Survey",
            "intro": "We're developing a new portfolio performance dashboard. Your feedback will shape the final product.",
            "questions": [
                {"id": "q1", "type": "rating", "text": "How likely are you to use a unified portfolio dashboard?", "scale_min": 1, "scale_max": 5, "scale_labels": ["Not at all likely", "Extremely likely"]},
                {"id": "q2", "type": "multiple_choice", "text": "Which features matter most to you?", "options": ["Real-time data", "Risk metrics", "Strategy comparison", "Mobile access", "Export/API"], "allow_multiple": True},
                {"id": "q3", "type": "open", "text": "What concerns do you have about this new dashboard?"},
            ],
        }
        survey_path = run_dir / "survey.json"
        survey_path.write_text(json.dumps(survey_data, indent=2), encoding="utf-8")
        logger.info("[DRY RUN] Using template survey")
    else:
        survey_path = await design_survey(
            brief_path, run_dir,
            analyst_id="marketing_researcher",
            backend=backend, model=model,
            agentic=agentic, max_steps=max_steps,
        )

    pipeline_meta["steps"].append({"step": 2, "agent": "marketing_researcher", "output": "survey.json"})
    _log_handoff("marketing_researcher", "customers", survey_path, run_dir)
    await _broadcast(broadcast_url, {
        "feedback_type": "step_complete", "run_id": run_dir.name,
        "step": 2, "agent": "marketing_researcher", "artifact": "survey.json",
        "elapsed_ms": int((_time.monotonic() - _step_t0) * 1000),
    })

    # Step 3: Customer personas answer survey
    logger.info("")
    logger.info(f"STEP 3/5: {count} customer personas answer survey")
    logger.info("-" * 50)
    _step_t0 = _time.monotonic()
    await _broadcast(broadcast_url, {
        "feedback_type": "step_start", "run_id": run_dir.name,
        "step": 3, "agent": "customers", "total": count,
        "message": f"{count} customer personas are answering the survey...",
    })

    from survey_runner import run_survey

    if dry_run:
        from archetype_generator import load_profiles as _load_profiles
        import random as _random

        _profiles = _load_profiles()
        _personas = generate_personas(count, profiles=_profiles, seed=seed)
        survey_loaded = json.loads((run_dir / "survey.json").read_text(encoding="utf-8"))
        questions = survey_loaded.get("questions", [])
        dry_responses: list[dict[str, Any]] = []
        for persona in _personas:
            answers = []
            for q in questions:
                if q["type"] == "rating":
                    val = _random.randint(q.get("scale_min", 1), q.get("scale_max", 5))
                elif q["type"] == "multiple_choice":
                    opts = q.get("options", ["N/A"])
                    if q.get("allow_multiple"):
                        val = _random.sample(opts, k=min(_random.randint(1, 3), len(opts)))
                    else:
                        val = _random.choice(opts)
                else:
                    val = f"[Dry run response from {persona['archetype_label']}]"
                answers.append({"question_id": q["id"], "value": val})
            dry_responses.append({
                "persona_id": persona["persona_id"],
                "archetype_id": persona["archetype_id"],
                "archetype_label": persona["archetype_label"],
                "answers": answers,
                "error": False,
            })
        responses_path = run_dir / "survey_responses.json"
        responses_path.write_text(json.dumps(dry_responses, indent=2), encoding="utf-8")
        (run_dir / "personas.json").write_text(json.dumps(_personas, indent=2), encoding="utf-8")
        logger.info(f"[DRY RUN] Generated {len(dry_responses)} template survey responses")
    else:
        responses_path = await run_survey(
            survey_path, run_dir,
            count=count, batch_size=batch_size,
            seed=seed, model=model, models=models,
        )

    pipeline_meta["steps"].append({"step": 3, "agent": "customers", "output": "survey_responses.json"})
    _log_handoff("customers", "marketing_researcher", responses_path, run_dir)
    await _broadcast(broadcast_url, {
        "feedback_type": "step_complete", "run_id": run_dir.name,
        "step": 3, "agent": "customers", "artifact": "survey_responses.json",
        "count": count,
        "elapsed_ms": int((_time.monotonic() - _step_t0) * 1000),
    })

    # Step 4: Marketing compiles findings
    logger.info("")
    logger.info("STEP 4/5: Marketing Researcher compiles findings")
    logger.info("-" * 50)
    _step_t0 = _time.monotonic()
    await _broadcast(broadcast_url, {
        "feedback_type": "step_start", "run_id": run_dir.name,
        "step": 4, "agent": "marketing_researcher",
        "message": "Marketing Researcher is compiling findings...",
    })

    from marketing_agent import compile_findings

    if dry_run:
        mkt_report_text = (
            "# Marketing Research Report\n\n"
            "## Research Summary\nDry-run template report.\n\n"
            "## Quantitative Findings\nTemplate data.\n\n"
            "## Qualitative Themes\n1. Template theme.\n\n"
            "## Recommendations for Product\n- Template recommendation.\n"
        )
        mkt_report_path = run_dir / "marketing_report.md"
        mkt_report_path.write_text(mkt_report_text, encoding="utf-8")
        logger.info("[DRY RUN] Using template marketing report")
    else:
        mkt_report_path = await compile_findings(
            run_dir,
            analyst_id="marketing_researcher",
            backend=backend, model=model,
            agentic=agentic, max_steps=max_steps,
        )

    pipeline_meta["steps"].append({"step": 4, "agent": "marketing_researcher", "output": "marketing_report.md"})
    _log_handoff("marketing_researcher", "product_owner", mkt_report_path, run_dir)
    await _broadcast(broadcast_url, {
        "feedback_type": "step_complete", "run_id": run_dir.name,
        "step": 4, "agent": "marketing_researcher", "artifact": "marketing_report.md",
        "elapsed_ms": int((_time.monotonic() - _step_t0) * 1000),
    })

    # Step 5: PO final analysis
    logger.info("")
    logger.info("STEP 5/5: Product Owner final analysis")
    logger.info("-" * 50)
    _step_t0 = _time.monotonic()
    await _broadcast(broadcast_url, {
        "feedback_type": "step_start", "run_id": run_dir.name,
        "step": 5, "agent": "product_owner",
        "message": "Product Owner is writing the final analysis...",
    })

    from po_analyst import run_po_analysis

    if dry_run:
        from po_analyst import DRY_RUN_REPORT
        analysis_path = run_dir / "po_analysis.md"
        header = (
            f"# Product Owner Analysis\n\n"
            f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"**Mode:** dry-run\n**Data mode:** survey\n\n---\n\n"
        )
        analysis_path.write_text(header + DRY_RUN_REPORT, encoding="utf-8")
        logger.info("[DRY RUN] Using template PO analysis")
    else:
        analysis_path = await run_po_analysis(
            run_dir,
            analyst_id="product_owner",
            backend=backend, model=model,
            agentic=agentic, max_steps=max_steps,
        )

    pipeline_meta["steps"].append({"step": 5, "agent": "product_owner", "output": "po_analysis.md"})
    pipeline_meta["completed"] = datetime.now().isoformat()
    (run_dir / "pipeline_meta.json").write_text(json.dumps(pipeline_meta, indent=2), encoding="utf-8")

    await _broadcast(broadcast_url, {
        "feedback_type": "step_complete", "run_id": run_dir.name,
        "step": 5, "agent": "product_owner", "artifact": "po_analysis.md",
        "elapsed_ms": int((_time.monotonic() - _step_t0) * 1000),
    })

    logger.info("")
    logger.info("=" * 70)
    logger.info("RESEARCH PIPELINE COMPLETE")
    logger.info(f"  Run dir: {run_dir}")
    logger.info("  Artifacts:")
    for f in sorted(run_dir.iterdir()):
        if f.is_file():
            logger.info(f"    {f.name} ({f.stat().st_size:,} bytes)")
    logger.info("=" * 70)

    await _broadcast(broadcast_url, {
        "feedback_type": "pipeline_complete", "run_id": run_dir.name,
        "elapsed_ms": int((_time.monotonic() - _pipeline_t0) * 1000),
    })


async def _run_feedback_mode(
    feature_text: str,
    personas: list[dict[str, Any]],
    run_dir: Path,
    batch_size: int,
    llm_model: str,
    temperature: float,
    max_tokens: int,
    backend: str,
    agentic: bool,
    max_steps: int,
    dry_run: bool,
    seed: int | None,
    mem: Any,
    run_meta: dict[str, Any] | None,
    run_key: str | None,
    po_analysis: bool,
    po_backend: str | None,
    po_model: str | None,
    po_analyst_id: str,
    po_agentic: bool,
    po_max_steps: int,
) -> None:
    """Open-ended feedback: customer conversations -> aggregator report -> PO analysis."""
    all_responses: list[dict[str, Any]] = []

    if dry_run:
        logger.info("DRY RUN mode — generating mock responses from templates")
        if seed is not None:
            random.seed(seed + 1000)
        for persona in personas:
            resp = generate_dry_run_response(persona)
            all_responses.append(resp)
            logger.info(
                f"  [{resp['persona_id']}] sentiment={resp['sentiment']} "
                f"would_use={resp['would_use']}"
            )
    elif agentic and backend == "bedrock":
        from agent_loop import AgentPersonaRunner

        if boto3 is None:
            logger.error("boto3 not installed — cannot use bedrock agentic backend.")
            return

        model_list = [m.strip() for m in llm_model.split(",")]
        for i, persona in enumerate(personas):
            persona["_bedrock_model"] = model_list[i % len(model_list)]

        model_counts: dict[str, int] = {}
        for p in personas:
            m = p["_bedrock_model"]
            model_counts[m] = model_counts.get(m, 0) + 1
        logger.info(f"AGENTIC mode | max_steps={max_steps} | Models: {model_counts}")

        for batch_start in range(0, len(personas), batch_size):
            batch = personas[batch_start:batch_start + batch_size]
            batch_end = min(batch_start + batch_size, len(personas))
            logger.info(f"Processing agentic batch {batch_start + 1}-{batch_end} of {len(personas)}...")

            runners = [
                AgentPersonaRunner(
                    persona=p,
                    feature_text=feature_text,
                    model=llm_model,
                    max_steps=max_steps,
                    temperature=temperature,
                    max_tokens=max_tokens,
                ).run()
                for p in batch
            ]
            results = await asyncio.gather(*runners, return_exceptions=True)

            for idx, r in enumerate(results):
                if isinstance(r, Exception):
                    logger.error(f"Agentic task exception: {r}")
                    continue
                resp = r.feedback_json
                persona = batch[idx]
                resp.setdefault("persona_id", persona["persona_id"])
                resp["archetype_id"] = persona["archetype_id"]
                resp["archetype_label"] = persona["archetype_label"]
                resp["_model"] = r.model
                resp["_latency_ms"] = r.total_latency_ms
                resp["_tool_calls"] = r.tool_calls
                resp["_steps_used"] = r.steps_used
                resp["_skills"] = r.skills
                resp["_reasoning_trace"] = r.reasoning_trace
                if r.error:
                    resp["error"] = True
                all_responses.append(resp)
                logger.info(
                    f"  [{resp['persona_id']}] [{r.model}] "
                    f"sentiment={resp.get('sentiment')} tools={r.tool_calls} "
                    f"steps={r.steps_used} {r.total_latency_ms}ms"
                )

            if batch_end < len(personas):
                await asyncio.sleep(2)

    else:
        backend_dispatch = {
            "gemini": call_gemini_direct,
            "minimax": call_minimax_direct,
            "litellm": call_litellm_proxy,
            "bedrock": call_bedrock_converse,
        }

        if backend == "bedrock":
            if boto3 is None:
                logger.error("boto3 not installed — cannot use bedrock backend.")
                return

            model_list = [m.strip() for m in llm_model.split(",")]
            if len(model_list) > 1:
                for i, persona in enumerate(personas):
                    persona["_bedrock_model"] = model_list[i % len(model_list)]
                model_counts: dict[str, int] = {}
                for p in personas:
                    m = p["_bedrock_model"]
                    model_counts[m] = model_counts.get(m, 0) + 1
                logger.info(f"Backend: bedrock | Multi-model split: {model_counts}")
            else:
                for persona in personas:
                    persona["_bedrock_model"] = model_list[0]
                logger.info(f"Backend: bedrock | Model: {model_list[0]}")

            call_fn = call_bedrock_converse
            client_ctx = None
        else:
            if httpx is None:
                logger.error("httpx not installed — cannot make LLM calls.")
                return
            call_fn = backend_dispatch[backend]
            display_model = llm_model if backend != "minimax" else MINIMAX_MODEL
            logger.info(f"Backend: {backend} | Model: {display_model}")
            client_ctx = httpx.AsyncClient(
                timeout=httpx.Timeout(120.0, connect=10.0),
                verify=False if backend in ("gemini", "minimax") else True,
            )

        client = None
        if client_ctx is not None:
            client = await client_ctx.__aenter__()

        try:
            for batch_start in range(0, len(personas), batch_size):
                batch = personas[batch_start:batch_start + batch_size]
                batch_end = min(batch_start + batch_size, len(personas))
                logger.info(f"Processing batch {batch_start + 1}-{batch_end} of {len(personas)}...")

                tasks = [
                    call_fn(client, persona, feature_text, llm_model, temperature, max_tokens)
                    for persona in batch
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                for r in results:
                    if isinstance(r, Exception):
                        logger.error(f"Batch task exception: {r}")
                        continue
                    all_responses.append(r)
                    model_tag = f" [{r.get('_model', '')}]" if r.get("_model") else ""
                    logger.info(
                        f"  [{r['persona_id']}]{model_tag} sentiment={r.get('sentiment')} "
                        f"would_use={r.get('would_use')}"
                    )

                if batch_end < len(personas):
                    await asyncio.sleep(1)
        finally:
            if client_ctx is not None:
                await client_ctx.__aexit__(None, None, None)

    raw_path = run_dir / "raw_responses.json"
    raw_path.write_text(json.dumps(all_responses, indent=2), encoding="utf-8")
    logger.info(f"Raw responses saved → {raw_path}")

    if mem is not None and run_meta is not None and run_key is not None:
        try:
            run_meta["status"] = "completed"
            run_meta["responses"] = all_responses
            run_meta["completed_at"] = datetime.now().isoformat()
            await mem.set_shared(run_key, run_meta)
        except Exception:
            pass

    (run_dir / "personas.json").write_text(json.dumps(personas, indent=2), encoding="utf-8")

    logger.info(f"Simulation complete: {len(all_responses)}/{len(personas)} responses collected")
    logger.info(f"Output directory: {run_dir}")

    try:
        from aggregator import generate_report
        report_path = generate_report(all_responses, run_dir)
        logger.info(f"Report generated → {report_path}")
    except Exception as e:
        logger.warning(f"Auto-aggregation skipped: {e}. Run aggregator.py manually.")

    if po_analysis:
        try:
            from po_analyst import run_po_analysis
            po_backend_resolved = po_backend or backend
            if po_backend_resolved not in ("gemini", "bedrock"):
                po_backend_resolved = "bedrock"
            po_path = await run_po_analysis(
                run_dir=run_dir,
                analyst_id=po_analyst_id,
                backend=po_backend_resolved,
                model=po_model,
                dry_run=False,
                agentic=po_agentic,
                max_steps=po_max_steps,
            )
            logger.info(f"Analyst report generated -> {po_path}")
        except Exception as e:
            logger.warning(f"Analyst report skipped: {e}. Run po_analyst.py manually.")


async def run_simulation(
    feature_text: str,
    count: int = 10,
    batch_size: int = 10,
    seed: int | None = None,
    model: str | None = None,
    models: str | None = None,
    dry_run: bool = False,
    backend: str = "gemini",
    agentic: bool = False,
    max_steps: int = 5,
    mode: str = "survey",
    po_analysis: bool = True,
    po_backend: str | None = None,
    po_model: str | None = None,
    po_analyst_id: str = "product_owner",
    po_agentic: bool = True,
    po_max_steps: int = 5,
    broadcast_url: str | None = None,
) -> Path:
    """Run the full feedback simulation and return the output directory path."""
    profiles = load_profiles()
    defaults = profiles.get("defaults", {})
    model_pool = defaults.get("model_pool", [])
    if model and "," in model:
        llm_model = model
    elif model:
        llm_model = model
    elif model_pool:
        llm_model = ",".join(model_pool)
    else:
        llm_model = defaults.get("model", "deepseek.v3.2")
    temperature = defaults.get("temperature", 0.8)
    max_tokens = defaults.get("max_tokens", 512)

    personas = generate_personas(count, profiles=profiles, seed=seed)
    logger.info(f"Generated {len(personas)} personas across archetypes")

    archetype_counts: dict[str, int] = {}
    for p in personas:
        archetype_counts[p["archetype_label"]] = archetype_counts.get(p["archetype_label"], 0) + 1
    logger.info(f"Distribution: {archetype_counts}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = OUTPUT_BASE / f"run_{timestamp}"
    run_dir.mkdir(parents=True, exist_ok=True)

    mem = None
    run_key: str | None = None
    run_meta: dict[str, Any] | None = None
    if SharedMemory is not None:
        try:
            mem = SharedMemory()
            run_key = f"feedback_run_{timestamp}"
            run_meta = {
                "timestamp": timestamp,
                "feature_text": feature_text[:500],
                "total_personas": len(personas),
                "model": llm_model if not dry_run else "dry-run",
                "status": "running",
                "responses": [],
            }
            await mem.set_shared(run_key, run_meta)
        except Exception as e:
            logger.warning(f"SharedMemory unavailable ({e}), continuing without Redis")
            mem = None

    (run_dir / "feature.txt").write_text(feature_text, encoding="utf-8")

    if mode == "survey":
        await _run_survey_pipeline(
            feature_text=feature_text,
            run_dir=run_dir,
            count=count,
            batch_size=batch_size,
            seed=seed,
            model=model,
            models=models,
            backend=backend,
            agentic=agentic,
            max_steps=max_steps,
            dry_run=dry_run,
            broadcast_url=broadcast_url,
        )
    else:
        await _run_feedback_mode(
            feature_text=feature_text,
            personas=personas,
            run_dir=run_dir,
            batch_size=batch_size,
            llm_model=llm_model,
            temperature=temperature,
            max_tokens=max_tokens,
            backend=backend,
            agentic=agentic,
            max_steps=max_steps,
            dry_run=dry_run,
            seed=seed,
            mem=mem if mem is not None else None,
            run_meta=run_meta if mem is not None else None,
            run_key=run_key if mem is not None else None,
            po_analysis=po_analysis,
            po_backend=po_backend,
            po_model=po_model,
            po_analyst_id=po_analyst_id,
            po_agentic=po_agentic,
            po_max_steps=po_max_steps,
        )

    if mem is not None:
        await mem.close()
    global _broadcast_client
    if _broadcast_client is not None:
        await _broadcast_client.aclose()
        _broadcast_client = None
    return run_dir


def main():
    parser = argparse.ArgumentParser(description="Customer Feedback Simulator")
    parser.add_argument("--feature", type=str, required=True, help="Path to feature announcement text file")
    parser.add_argument("--count", type=int, default=10, help="Number of simulated customers")
    parser.add_argument("--batch-size", type=int, default=10, help="Concurrent LLM calls per batch")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility")
    parser.add_argument("--model", type=str, default=None, help="LLM model override")
    parser.add_argument("--models", type=str, default=None,
                        help="Comma-separated model IDs for customer survey round-robin (survey mode)")
    parser.add_argument("--mode", type=str, default="survey", choices=["survey", "feedback"],
                        help="'survey' (default): PO brief -> Marketing survey -> customers -> compile -> PO analysis. "
                             "'feedback': open-ended customer conversations + PO analysis")
    parser.add_argument("--dry-run", action="store_true", help="Generate mock responses without calling LLM")
    parser.add_argument("--backend", type=str, default="gemini",
                        choices=["gemini", "minimax", "litellm", "bedrock"],
                        help="LLM backend: 'gemini' | 'minimax' | 'litellm' | 'bedrock'")
    parser.add_argument("--region", type=str, default=None,
                        help="AWS region for bedrock backend (default: ap-southeast-2)")
    parser.add_argument("--agentic", action="store_true",
                        help="Enable agentic mode: personas use ReAct loop with tool calling (bedrock only)")
    parser.add_argument("--max-steps", type=int, default=5,
                        help="Max ReAct steps per agent in agentic mode (default: 5)")
    parser.add_argument("--po", action="store_true", default=True,
                        help="Run PO analysis after feedback collection (default: on)")
    parser.add_argument("--no-po", dest="po", action="store_false",
                        help="Skip PO analysis step")
    parser.add_argument("--po-analyst", type=str, default="product_owner",
                        help="Analyst persona ID from analysts.json (default: product_owner)")
    parser.add_argument("--po-backend", type=str, default=None, choices=["gemini", "bedrock"],
                        help="LLM backend for analyst (defaults to analysts.json, then --backend)")
    parser.add_argument("--po-model", type=str, default=None,
                        help="LLM model override for analyst")
    parser.add_argument("--po-agentic", action="store_true", default=True,
                        help="Enable agentic mode for analyst (default: True)")
    parser.add_argument("--po-no-agentic", dest="po_agentic", action="store_false",
                        help="Disable agentic mode for analyst, run single-shot")
    parser.add_argument("--po-max-steps", type=int, default=5,
                        help="Max ReAct steps for analyst agent (default: 5)")
    parser.add_argument("--broadcast-url", type=str, default=None,
                        help="URL to POST pipeline progress events (e.g. http://localhost:8000/api/monitor/feedback/broadcast)")
    args = parser.parse_args()

    if args.region:
        os.environ["AWS_DEFAULT_REGION"] = args.region

    feature_path = Path(args.feature)
    if not feature_path.exists():
        logger.error(f"Feature file not found: {feature_path}")
        sys.exit(1)

    feature_text = feature_path.read_text(encoding="utf-8").strip()
    if not feature_text:
        logger.error("Feature file is empty")
        sys.exit(1)

    mode_label = "DRY RUN" if args.dry_run else ("AGENTIC" if args.agentic else "LIVE")
    logger.info(f"[{mode_label}] [{args.mode.upper()} MODE] Feature: {feature_path.name} ({len(feature_text)} chars)")
    if args.mode == "survey":
        logger.info(f"Pipeline: PO brief -> Marketing survey -> {args.count} customers -> Marketing compile -> PO analysis")
    else:
        logger.info(f"Simulating {args.count} customers (batch size {args.batch_size})")

    run_dir = asyncio.run(
        run_simulation(
            feature_text=feature_text,
            count=args.count,
            batch_size=args.batch_size,
            seed=args.seed,
            model=args.model,
            models=args.models,
            dry_run=args.dry_run,
            backend=args.backend,
            agentic=args.agentic,
            max_steps=args.max_steps,
            mode=args.mode,
            po_analysis=args.po,
            po_backend=args.po_backend,
            po_model=args.po_model,
            po_analyst_id=args.po_analyst,
            po_agentic=args.po_agentic,
            po_max_steps=args.po_max_steps,
            broadcast_url=args.broadcast_url,
        )
    )

    print(f"\nDone. Results in: {run_dir}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logger.exception("Pipeline crashed: %s", exc)
        _url = None
        for a in sys.argv:
            if a.startswith("http"):
                _url = a
                break
            if a == "--broadcast-url":
                idx = sys.argv.index(a)
                if idx + 1 < len(sys.argv):
                    _url = sys.argv[idx + 1]
                    break
        if _url:
            import asyncio as _aio
            _aio.run(_broadcast(_url, {
                "feedback_type": "error",
                "message": str(exc),
            }))
        sys.exit(1)
