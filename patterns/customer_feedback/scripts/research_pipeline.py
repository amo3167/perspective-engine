"""
Research Pipeline — PO-initiated multi-agent research workflow.

DEPRECATED: Use feedback_simulator.py --mode survey instead.
This standalone entry point is kept for backward compatibility.

5-step pipeline with explicit agent-to-agent artifact handoffs:
    Step 1: PO writes research brief       -> research_brief.md
    Step 2: Marketing designs survey        -> survey.json
    Step 3: Customers answer survey         -> survey_responses.json
    Step 4: Marketing compiles findings     -> marketing_report.md
    Step 5: PO final analysis               -> po_analysis.md

Usage (prefer feedback_simulator.py --mode survey):
    python feedback_simulator.py --feature path/to/feature.md --count 20 --mode survey
    python feedback_simulator.py --feature path/to/feature.md --count 20 --mode survey --backend bedrock

Legacy usage (deprecated):
    python research_pipeline.py --feature path/to/feature.md --count 20
"""

import sys
import os
import json
import asyncio
import logging
import argparse
from datetime import datetime
from pathlib import Path
from typing import Any

from pe_layout import ensure_sys_path, load_dotenv_layers

ensure_sys_path()
load_dotenv_layers()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [pipeline] - %(levelname)s - %(message)s",
)
logger = logging.getLogger("research_pipeline")

SKILL_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_BASE = SKILL_ROOT / "output"


def log_handoff(from_agent: str, to_agent: str, artifact: Path, run_dir: Path) -> None:
    """Log an agent-to-agent handoff to the pipeline trace."""
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


async def run_research_pipeline(
    feature_text: str,
    count: int = 20,
    batch_size: int = 10,
    seed: int | None = None,
    backend: str = "bedrock",
    model: str | None = None,
    models: str | None = None,
    agentic: bool = True,
    max_steps: int = 5,
    dry_run: bool = False,
) -> Path:
    """Run the full 5-step research pipeline. Returns the run directory."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = OUTPUT_BASE / f"run_{timestamp}"
    run_dir.mkdir(parents=True, exist_ok=True)

    (run_dir / "feature.txt").write_text(feature_text, encoding="utf-8")

    pipeline_meta = {
        "type": "research_pipeline",
        "timestamp": timestamp,
        "feature_length": len(feature_text),
        "count": count,
        "backend": backend,
        "model": model,
        "agentic": agentic,
        "dry_run": dry_run,
        "steps": [],
    }

    logger.info("=" * 70)
    logger.info("RESEARCH PIPELINE STARTED")
    logger.info(f"  Run dir: {run_dir}")
    logger.info(f"  Respondents: {count} | Backend: {backend} | Agentic: {agentic}")
    logger.info("=" * 70)

    # ------------------------------------------------------------------
    # Step 1: PO writes research brief
    # ------------------------------------------------------------------
    logger.info("")
    logger.info("STEP 1/5: Product Owner writes research brief")
    logger.info("-" * 50)

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
            feature_text,
            run_dir,
            analyst_id="product_owner",
            backend=backend,
            model=model,
            agentic=agentic,
            max_steps=max_steps,
        )

    pipeline_meta["steps"].append(
        {"step": 1, "agent": "product_owner", "output": "research_brief.md"}
    )
    log_handoff("product_owner", "marketing_researcher", brief_path, run_dir)

    # ------------------------------------------------------------------
    # Step 2: Marketing designs survey
    # ------------------------------------------------------------------
    logger.info("")
    logger.info("STEP 2/5: Marketing Researcher designs survey")
    logger.info("-" * 50)

    from marketing_agent import design_survey

    if dry_run:
        survey_data = {
            "title": "Portfolio Dashboard Feedback Survey",
            "intro": "We're developing a new portfolio performance dashboard. Your feedback will shape the final product.",
            "questions": [
                {
                    "id": "q1",
                    "type": "rating",
                    "text": "How likely are you to use a unified portfolio dashboard?",
                    "scale_min": 1,
                    "scale_max": 5,
                    "scale_labels": ["Not at all likely", "Extremely likely"],
                },
                {
                    "id": "q2",
                    "type": "rating",
                    "text": "How satisfied are you with your current portfolio tracking tools?",
                    "scale_min": 1,
                    "scale_max": 5,
                    "scale_labels": ["Very dissatisfied", "Very satisfied"],
                },
                {
                    "id": "q3",
                    "type": "multiple_choice",
                    "text": "Which features matter most to you?",
                    "options": [
                        "Real-time data",
                        "Risk metrics",
                        "Strategy comparison",
                        "Mobile access",
                        "Export/API",
                    ],
                    "allow_multiple": True,
                },
                {
                    "id": "q4",
                    "type": "multiple_choice",
                    "text": "How do you primarily access trading tools?",
                    "options": [
                        "Desktop browser",
                        "Mobile app",
                        "Both equally",
                        "API/programmatic",
                    ],
                    "allow_multiple": False,
                },
                {
                    "id": "q5",
                    "type": "open",
                    "text": "What concerns, if any, do you have about this new dashboard?",
                },
                {
                    "id": "q6",
                    "type": "open",
                    "text": "What feature or improvement would make this dashboard indispensable for you?",
                },
            ],
        }
        survey_path = run_dir / "survey.json"
        survey_path.write_text(json.dumps(survey_data, indent=2), encoding="utf-8")
        logger.info("[DRY RUN] Using template survey")
    else:
        survey_path = await design_survey(
            brief_path,
            run_dir,
            analyst_id="marketing_researcher",
            backend=backend,
            model=model,
            agentic=agentic,
            max_steps=max_steps,
        )

    pipeline_meta["steps"].append(
        {"step": 2, "agent": "marketing_researcher", "output": "survey.json"}
    )
    log_handoff("marketing_researcher", "customers", survey_path, run_dir)

    # ------------------------------------------------------------------
    # Step 3: Customer personas answer survey
    # ------------------------------------------------------------------
    logger.info("")
    logger.info(f"STEP 3/5: {count} customer personas answer survey")
    logger.info("-" * 50)

    from survey_runner import run_survey

    if dry_run:
        from archetype_generator import generate_personas, load_profiles
        import random

        profiles = load_profiles()
        personas = generate_personas(count, profiles=profiles, seed=seed)
        survey_data_loaded = json.loads(
            (run_dir / "survey.json").read_text(encoding="utf-8")
        )
        questions = survey_data_loaded.get("questions", [])
        dry_responses: list[dict[str, Any]] = []
        for persona in personas:
            answers = []
            for q in questions:
                if q["type"] == "rating":
                    val = random.randint(q.get("scale_min", 1), q.get("scale_max", 5))
                elif q["type"] == "multiple_choice":
                    opts = q.get("options", ["N/A"])
                    if q.get("allow_multiple"):
                        val = random.sample(
                            opts, k=min(random.randint(1, 3), len(opts))
                        )
                    else:
                        val = random.choice(opts)
                else:
                    val = f"[Dry run response from {persona['archetype_label']}]"
                answers.append({"question_id": q["id"], "value": val})
            dry_responses.append(
                {
                    "persona_id": persona["persona_id"],
                    "archetype_id": persona["archetype_id"],
                    "archetype_label": persona["archetype_label"],
                    "answers": answers,
                    "error": False,
                }
            )
        responses_path = run_dir / "survey_responses.json"
        responses_path.write_text(json.dumps(dry_responses, indent=2), encoding="utf-8")
        (run_dir / "personas.json").write_text(
            json.dumps(personas, indent=2), encoding="utf-8"
        )
        logger.info(
            f"[DRY RUN] Generated {len(dry_responses)} template survey responses"
        )
    else:
        responses_path = await run_survey(
            survey_path,
            run_dir,
            count=count,
            batch_size=batch_size,
            seed=seed,
            model=model,
            models=models,
        )

    pipeline_meta["steps"].append(
        {"step": 3, "agent": "customers", "output": "survey_responses.json"}
    )
    log_handoff("customers", "marketing_researcher", responses_path, run_dir)

    # ------------------------------------------------------------------
    # Step 4: Marketing compiles findings
    # ------------------------------------------------------------------
    logger.info("")
    logger.info("STEP 4/5: Marketing Researcher compiles findings")
    logger.info("-" * 50)

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
            backend=backend,
            model=model,
            agentic=agentic,
            max_steps=max_steps,
        )

    pipeline_meta["steps"].append(
        {"step": 4, "agent": "marketing_researcher", "output": "marketing_report.md"}
    )
    log_handoff("marketing_researcher", "product_owner", mkt_report_path, run_dir)

    # ------------------------------------------------------------------
    # Step 5: PO final analysis
    # ------------------------------------------------------------------
    logger.info("")
    logger.info("STEP 5/5: Product Owner final analysis")
    logger.info("-" * 50)

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
            backend=backend,
            model=model,
            agentic=agentic,
            max_steps=max_steps,
        )

    pipeline_meta["steps"].append(
        {"step": 5, "agent": "product_owner", "output": "po_analysis.md"}
    )

    pipeline_meta["completed"] = datetime.now().isoformat()
    (run_dir / "pipeline_meta.json").write_text(
        json.dumps(pipeline_meta, indent=2), encoding="utf-8"
    )

    logger.info("")
    logger.info("=" * 70)
    logger.info("RESEARCH PIPELINE COMPLETE")
    logger.info(f"  Run dir: {run_dir}")
    logger.info("  Artifacts:")
    for f in sorted(run_dir.iterdir()):
        if f.is_file():
            logger.info(f"    {f.name} ({f.stat().st_size:,} bytes)")
    logger.info("=" * 70)

    return run_dir


def main():
    import warnings

    warnings.warn(
        "research_pipeline.py is deprecated. Use: feedback_simulator.py --mode survey",
        DeprecationWarning,
        stacklevel=2,
    )
    logger.warning("DEPRECATED: Use feedback_simulator.py --mode survey instead.")

    parser = argparse.ArgumentParser(
        description="Research Pipeline (DEPRECATED — use feedback_simulator.py --mode survey)"
    )
    parser.add_argument(
        "--feature",
        type=str,
        required=True,
        help="Path to feature announcement text file",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=20,
        help="Number of survey respondents (default: 20)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=10,
        help="Concurrent LLM calls per batch (default: 10)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducible persona generation",
    )
    parser.add_argument(
        "--backend",
        type=str,
        default="bedrock",
        choices=["gemini", "bedrock"],
        help="LLM backend for agent calls (default: bedrock)",
    )
    parser.add_argument(
        "--model", type=str, default=None, help="LLM model override for all agents"
    )
    parser.add_argument(
        "--models",
        type=str,
        default=None,
        help="Comma-separated model IDs for customer survey round-robin",
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
        help="Disable agentic mode for all agents",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=5,
        help="Max ReAct steps per agent (default: 5)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Use template outputs without calling LLMs",
    )
    parser.add_argument(
        "--region", type=str, default=None, help="AWS region for bedrock backend"
    )
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
    logger.info(
        f"[{mode_label}] Feature: {feature_path.name} ({len(feature_text)} chars)"
    )
    logger.info(
        f"Pipeline: PO brief -> Marketing survey -> {args.count} customers -> Marketing compile -> PO analysis"
    )

    run_dir = asyncio.run(
        run_research_pipeline(
            feature_text=feature_text,
            count=args.count,
            batch_size=args.batch_size,
            seed=args.seed,
            backend=args.backend,
            model=args.model,
            models=args.models,
            agentic=args.agentic,
            max_steps=args.max_steps,
            dry_run=args.dry_run,
        )
    )

    print(f"\nDone. Results in: {run_dir}")


if __name__ == "__main__":
    main()
