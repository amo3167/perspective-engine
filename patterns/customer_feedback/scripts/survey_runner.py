"""
Survey Runner — Distributes a survey.json to customer personas and collects responses.

Reuses archetype_generator for persona sampling and batched async Bedrock Converse
calls (same pattern as feedback_simulator.py). Personas answer survey questions in
character, producing structured per-question answers.

Usage:
    python survey_runner.py --survey path/to/survey.json --run-dir output/run_XXX --count 20
"""

import sys
import os
import json
import asyncio
import logging
import argparse
import re
import random
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

from archetype_generator import generate_personas, load_profiles

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [survey] - %(levelname)s - %(message)s",
)
logger = logging.getLogger("survey_runner")

BEDROCK_REGION = os.environ.get("AWS_DEFAULT_REGION", "ap-southeast-2")
BEDROCK_TIMEOUT = BotoConfig(read_timeout=600, retries={"max_attempts": 2}) if BotoConfig else None


def _get_bedrock_client():
    if not hasattr(_get_bedrock_client, "_client"):
        _get_bedrock_client._client = boto3.client(
            "bedrock-runtime", region_name=BEDROCK_REGION, config=BEDROCK_TIMEOUT
        )
    return _get_bedrock_client._client


def _build_survey_system_prompt(persona: dict[str, Any]) -> str:
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
        f"You are a real customer completing a product feedback survey.\n"
        f"Your persona: {persona['soul']}\n"
        f"Your response style: {persona['response_style']}\n"
        f"Your age: {persona['age']} | Tech level: {persona['tech_level']} | "
        f"Patience (1-10): {persona['patience']} | Language style: {persona['language_style']}\n"
        f"Your general satisfaction bias: {persona['satisfaction_bias']}"
        f"{context_block}\n\n"
        f"Stay fully in character. Answer each question honestly as this person would.\n"
        f"Do NOT break character or mention that you are an AI.\n\n"
        f"You MUST respond with ONLY a valid JSON object (no markdown fences, no extra text).\n"
        f"Use this exact schema:\n"
        f'{{\n'
        f'  "answers": [\n'
        f'    {{ "question_id": "q1", "value": <your answer> }},\n'
        f'    {{ "question_id": "q2", "value": <your answer> }}\n'
        f'  ]\n'
        f'}}\n\n'
        f"For **rating** questions: value is an integer within the specified scale.\n"
        f"For **multiple_choice** questions: value is a string (single) or array of strings (if allow_multiple).\n"
        f"For **open** questions: value is a string with your honest response (1-3 sentences).\n\n"
        f"Respond ONLY with the JSON object."
    )


def _build_survey_user_prompt(survey: dict[str, Any]) -> str:
    parts = [
        f"# {survey.get('title', 'Customer Survey')}\n",
        f"{survey.get('intro', '')}\n",
        "Please answer each question below:\n",
    ]

    for q in survey.get("questions", []):
        qtype = q["type"]
        parts.append(f"**{q['id']}** ({qtype}): {q['text']}")
        if qtype == "rating":
            scale_min = q.get("scale_min", 1)
            scale_max = q.get("scale_max", 5)
            labels = q.get("scale_labels", [])
            label_str = f" ({labels[0]} to {labels[-1]})" if len(labels) >= 2 else ""
            parts.append(f"  Scale: {scale_min}-{scale_max}{label_str}")
        elif qtype == "multiple_choice":
            options = q.get("options", [])
            allow_multi = q.get("allow_multiple", False)
            parts.append(f"  Options: {', '.join(options)}")
            if allow_multi:
                parts.append("  (Select all that apply)")
        parts.append("")

    parts.append("Provide your answers as a JSON object.")
    return "\n".join(parts)


def _parse_survey_response(raw: str) -> dict[str, Any] | None:
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


def _tag_survey_response(parsed: dict[str, Any], persona: dict[str, Any]) -> dict[str, Any]:
    return {
        "persona_id": persona["persona_id"],
        "archetype_id": persona["archetype_id"],
        "archetype_label": persona["archetype_label"],
        "answers": parsed.get("answers", []),
        "error": False,
    }


def _error_survey_response(persona: dict[str, Any]) -> dict[str, Any]:
    return {
        "persona_id": persona["persona_id"],
        "archetype_id": persona["archetype_id"],
        "archetype_label": persona["archetype_label"],
        "answers": [],
        "error": True,
        "error_msg": "LLM failed to produce valid survey response JSON",
    }


async def _call_bedrock_survey(
    persona: dict[str, Any],
    survey: dict[str, Any],
    model: str,
    temperature: float,
    max_tokens: int,
) -> dict[str, Any]:
    if boto3 is None:
        logger.error("boto3 not installed")
        return _error_survey_response(persona)

    bedrock = _get_bedrock_client()
    system_prompt = _build_survey_system_prompt(persona)
    user_prompt = _build_survey_user_prompt(survey)

    bedrock_model = persona.get("_bedrock_model", model)

    for attempt in range(3):
        try:
            resp = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: bedrock.converse(
                    modelId=bedrock_model,
                    system=[{"text": system_prompt}],
                    messages=[{"role": "user", "content": [{"text": user_prompt}]}],
                    inferenceConfig={"maxTokens": max_tokens * 4, "temperature": temperature},
                ),
            )
            raw = resp["output"]["message"]["content"][0]["text"]
            parsed = _parse_survey_response(raw)
            if parsed and "answers" in parsed:
                parsed["_model"] = bedrock_model
                parsed["_latency_ms"] = resp.get("metrics", {}).get("latencyMs", "?")
                return _tag_survey_response(parsed, persona)
            logger.warning(
                f"[{persona['persona_id']}] Attempt {attempt + 1}: invalid JSON from {bedrock_model}"
            )
        except Exception as e:
            if "Throttling" in str(type(e).__name__) or "ThrottlingException" in str(e):
                wait = 5 * (attempt + 1)
                logger.warning(f"[{persona['persona_id']}] Throttled. Waiting {wait}s...")
                await asyncio.sleep(wait)
            else:
                logger.error(f"[{persona['persona_id']}] Bedrock error: {e}")
                await asyncio.sleep(3)

    return _error_survey_response(persona)


async def run_survey(
    survey_path: Path,
    run_dir: Path,
    count: int = 20,
    batch_size: int = 10,
    seed: int | None = None,
    model: str | None = None,
    models: str | None = None,
    temperature: float = 0.8,
    max_tokens: int = 1024,
) -> Path:
    """Distribute survey to N customer personas and collect responses."""
    survey = json.loads(survey_path.read_text(encoding="utf-8"))
    profiles = load_profiles()
    defaults = profiles.get("defaults", {})
    model_pool_cfg = defaults.get("model_pool", [])
    llm_model = model or defaults.get("model", "deepseek.v3.2")

    personas = generate_personas(count, profiles=profiles, seed=seed)
    logger.info(f"Generated {len(personas)} survey respondents")

    model_pool: list[str] = []
    if models:
        model_pool = [m.strip() for m in models.split(",") if m.strip()]
    elif model_pool_cfg:
        model_pool = list(model_pool_cfg)
    if model_pool:
        for i, p in enumerate(personas):
            p["_bedrock_model"] = model_pool[i % len(model_pool)]

    all_responses: list[dict[str, Any]] = []

    for batch_start in range(0, len(personas), batch_size):
        batch = personas[batch_start : batch_start + batch_size]
        batch_num = batch_start // batch_size + 1
        total_batches = (len(personas) + batch_size - 1) // batch_size
        logger.info(f"Survey batch {batch_num}/{total_batches} ({len(batch)} respondents)")

        tasks = [
            _call_bedrock_survey(p, survey, llm_model, temperature, max_tokens)
            for p in batch
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"[{batch[i]['persona_id']}] Exception: {result}")
                all_responses.append(_error_survey_response(batch[i]))
            else:
                all_responses.append(result)

    valid = sum(1 for r in all_responses if not r.get("error"))
    errors = sum(1 for r in all_responses if r.get("error"))
    logger.info(f"Survey complete: {valid} valid, {errors} errors out of {len(all_responses)}")

    responses_path = run_dir / "survey_responses.json"
    responses_path.write_text(json.dumps(all_responses, indent=2), encoding="utf-8")

    personas_path = run_dir / "personas.json"
    personas_path.write_text(json.dumps(personas, indent=2), encoding="utf-8")

    logger.info(f"Responses saved -> {responses_path}")
    return responses_path


def main():
    parser = argparse.ArgumentParser(description="Survey Runner — distribute survey to customer personas")
    parser.add_argument("--survey", type=str, required=True, help="Path to survey.json")
    parser.add_argument("--run-dir", type=str, required=True, help="Output run directory")
    parser.add_argument("--count", type=int, default=20, help="Number of respondents")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--model", type=str, default=None)
    parser.add_argument("--models", type=str, default=None,
                        help="Comma-separated model IDs for round-robin")
    args = parser.parse_args()

    responses_path = asyncio.run(
        run_survey(
            survey_path=Path(args.survey),
            run_dir=Path(args.run_dir),
            count=args.count,
            batch_size=args.batch_size,
            seed=args.seed,
            model=args.model,
            models=args.models,
        )
    )
    print(f"\nSurvey responses collected -> {responses_path}")


if __name__ == "__main__":
    main()
