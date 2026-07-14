"""
Feedback Aggregator — Analyzes raw customer feedback responses and produces a markdown report.

Can be invoked automatically by feedback_simulator.py or standalone:
    python aggregator.py --input output/run_YYYYMMDD_HHMMSS/raw_responses.json
"""

import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


def _sentiment_label(score: int) -> str:
    return {
        1: "Very Negative",
        2: "Negative",
        3: "Neutral",
        4: "Positive",
        5: "Very Positive",
    }.get(score, "Unknown")


def _bar(count: int, total: int, width: int = 20) -> str:
    if total == 0:
        return ""
    filled = round(count / total * width)
    return "█" * filled + "░" * (width - filled)


def compute_stats(responses: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [r for r in responses if not r.get("error")]
    total = len(valid)
    if total == 0:
        return {"error": "No valid responses to analyze"}

    sentiments = [r["sentiment"] for r in valid]
    sentiment_dist = Counter(sentiments)
    avg_sentiment = sum(sentiments) / total
    would_use_count = sum(1 for r in valid if r.get("would_use"))

    by_archetype: dict[str, dict[str, Any]] = {}
    for r in valid:
        arch = r.get("archetype_label", "Unknown")
        if arch not in by_archetype:
            by_archetype[arch] = {
                "sentiments": [],
                "would_use": 0,
                "count": 0,
                "concerns": [],
                "requests": [],
            }
        by_archetype[arch]["sentiments"].append(r["sentiment"])
        by_archetype[arch]["count"] += 1
        if r.get("would_use"):
            by_archetype[arch]["would_use"] += 1
        by_archetype[arch]["concerns"].extend(r.get("concerns", []))
        by_archetype[arch]["requests"].extend(r.get("feature_requests", []))

    all_concerns: list[str] = []
    all_requests: list[str] = []
    for r in valid:
        all_concerns.extend(r.get("concerns", []))
        all_requests.extend(r.get("feature_requests", []))

    top_concerns = Counter(
        c.lower().strip() for c in all_concerns if c.strip()
    ).most_common(10)
    top_requests = Counter(
        r.lower().strip() for r in all_requests if r.strip()
    ).most_common(10)

    quotes_positive = sorted(
        [r for r in valid if r["sentiment"] >= 4],
        key=lambda x: x["sentiment"],
        reverse=True,
    )
    quotes_negative = sorted(
        [r for r in valid if r["sentiment"] <= 2], key=lambda x: x["sentiment"]
    )

    by_model: dict[str, dict[str, Any]] = {}
    for r in valid:
        model_id = r.get("_model", "unknown")
        if model_id not in by_model:
            by_model[model_id] = {
                "sentiments": [],
                "would_use": 0,
                "count": 0,
                "latencies": [],
                "tool_calls": [],
            }
        by_model[model_id]["sentiments"].append(r["sentiment"])
        by_model[model_id]["count"] += 1
        if r.get("would_use"):
            by_model[model_id]["would_use"] += 1
        if r.get("_latency_ms") and r["_latency_ms"] != "?":
            by_model[model_id]["latencies"].append(r["_latency_ms"])
        if r.get("_tool_calls") is not None:
            by_model[model_id]["tool_calls"].append(r["_tool_calls"])

    tool_stats: dict[str, Any] | None = None
    agentic_responses = [r for r in valid if r.get("_tool_calls") is not None]
    if agentic_responses:
        total_tool_calls = sum(r["_tool_calls"] for r in agentic_responses)
        avg_tool_calls = total_tool_calls / len(agentic_responses)
        avg_steps = sum(r.get("_steps_used", 0) for r in agentic_responses) / len(
            agentic_responses
        )

        all_queries: list[str] = []
        for r in agentic_responses:
            for step in r.get("_reasoning_trace", []):
                for tool_entry in step.get("tools", []):
                    q = tool_entry.get("input", {}).get("query", "")
                    if q:
                        all_queries.append(q.lower().strip())

        by_archetype_tools: dict[str, list[int]] = {}
        for r in agentic_responses:
            arch = r.get("archetype_label", "Unknown")
            by_archetype_tools.setdefault(arch, []).append(r["_tool_calls"])

        tool_stats = {
            "total_tool_calls": total_tool_calls,
            "avg_tool_calls": avg_tool_calls,
            "avg_steps": avg_steps,
            "top_queries": Counter(all_queries).most_common(10),
            "by_archetype_tools": {
                k: sum(v) / len(v) for k, v in sorted(by_archetype_tools.items())
            },
        }

    return {
        "total": total,
        "errors": len(responses) - total,
        "avg_sentiment": avg_sentiment,
        "sentiment_dist": dict(sentiment_dist),
        "would_use_count": would_use_count,
        "would_use_pct": would_use_count / total * 100,
        "by_archetype": by_archetype,
        "by_model": by_model,
        "top_concerns": top_concerns,
        "top_requests": top_requests,
        "quotes_positive": quotes_positive[:3],
        "quotes_negative": quotes_negative[:3],
        "tool_stats": tool_stats,
    }


def render_report(stats: dict[str, Any], feature_text: str | None = None) -> str:
    lines: list[str] = []
    lines.append("# Customer Feedback Simulation Report")
    lines.append("")
    lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**Total Responses:** {stats['total']} ({stats['errors']} errors)")
    lines.append("")

    if feature_text:
        lines.append("## Feature Under Review")
        lines.append("")
        for line in feature_text.strip().split("\n")[:10]:
            lines.append(f"> {line}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Overall Sentiment")
    lines.append("")
    lines.append(f"**Average Score:** {stats['avg_sentiment']:.1f} / 5.0")
    lines.append(
        f"**Would Use:** {stats['would_use_count']}/{stats['total']} ({stats['would_use_pct']:.0f}%)"
    )
    lines.append("")

    lines.append("### Distribution")
    lines.append("")
    lines.append("| Score | Label | Count | Bar |")
    lines.append("|-------|-------|-------|-----|")
    for score in range(1, 6):
        count = stats["sentiment_dist"].get(score, 0)
        label = _sentiment_label(score)
        bar = _bar(count, stats["total"])
        lines.append(f"| {score} | {label} | {count} | {bar} |")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Breakdown by Archetype")
    lines.append("")
    lines.append("| Archetype | Count | Avg Sentiment | Would Use |")
    lines.append("|-----------|-------|---------------|-----------|")
    for arch, data in sorted(stats["by_archetype"].items()):
        avg = sum(data["sentiments"]) / data["count"] if data["count"] else 0
        wu = data["would_use"]
        lines.append(f"| {arch} | {data['count']} | {avg:.1f} | {wu}/{data['count']} |")
    lines.append("")

    if len(stats.get("by_model", {})) > 1:
        lines.append("---")
        lines.append("")
        lines.append("## Breakdown by Model")
        lines.append("")
        lines.append("| Model | Count | Avg Sentiment | Would Use | Avg Latency |")
        lines.append("|-------|-------|---------------|-----------|-------------|")
        for model_id, data in sorted(stats["by_model"].items()):
            avg = sum(data["sentiments"]) / data["count"] if data["count"] else 0
            wu = data["would_use"]
            lats = data.get("latencies", [])
            avg_lat = f"{sum(lats) / len(lats):.0f}ms" if lats else "n/a"
            parts = model_id.split(".")
            short_id = ".".join(parts[-2:]) if len(parts) >= 2 else model_id
            lines.append(
                f"| {short_id} | {data['count']} | {avg:.1f} | {wu}/{data['count']} | {avg_lat} |"
            )
        lines.append("")

    if stats.get("tool_stats"):
        ts = stats["tool_stats"]
        lines.append("---")
        lines.append("")
        lines.append("## Tool Usage (Agentic Mode)")
        lines.append("")
        lines.append(f"**Total Tool Calls:** {ts['total_tool_calls']}")
        lines.append(f"**Avg Calls/Agent:** {ts['avg_tool_calls']:.1f}")
        lines.append(f"**Avg Steps/Agent:** {ts['avg_steps']:.1f}")
        lines.append("")

        if ts.get("by_archetype_tools"):
            lines.append("### Tool Calls by Archetype")
            lines.append("")
            lines.append("| Archetype | Avg Tool Calls |")
            lines.append("|-----------|---------------|")
            for arch, avg_tc in ts["by_archetype_tools"].items():
                lines.append(f"| {arch} | {avg_tc:.1f} |")
            lines.append("")

        if ts.get("top_queries"):
            lines.append("### Top Search Queries")
            lines.append("")
            for query, count in ts["top_queries"]:
                lines.append(f"- **{query}** ({count}x)")
            lines.append("")

        if len(stats.get("by_model", {})) > 1:
            lines.append("### Tool Calls by Model")
            lines.append("")
            lines.append("| Model | Avg Tool Calls |")
            lines.append("|-------|---------------|")
            for model_id, data in sorted(stats["by_model"].items()):
                tcs = data.get("tool_calls", [])
                avg_tc = f"{sum(tcs) / len(tcs):.1f}" if tcs else "n/a"
                parts = model_id.split(".")
                short_id = ".".join(parts[-2:]) if len(parts) >= 2 else model_id
                lines.append(f"| {short_id} | {avg_tc} |")
            lines.append("")

    if stats["top_concerns"]:
        lines.append("---")
        lines.append("")
        lines.append("## Top Concerns")
        lines.append("")
        for concern, count in stats["top_concerns"]:
            lines.append(f"- **{concern}** ({count}x)")
        lines.append("")

    if stats["top_requests"]:
        lines.append("---")
        lines.append("")
        lines.append("## Top Feature Requests")
        lines.append("")
        for req, count in stats["top_requests"]:
            lines.append(f"- **{req}** ({count}x)")
        lines.append("")

    if stats["quotes_positive"]:
        lines.append("---")
        lines.append("")
        lines.append("## Notable Quotes")
        lines.append("")
        lines.append("### Most Positive")
        lines.append("")
        for q in stats["quotes_positive"]:
            feedback = q.get("feedback")
            if not feedback:
                continue  # a response is only guaranteed to carry 'sentiment'
            mp = q.get("_model", "").split(".")
            model_note = f" via {'.'.join(mp[-2:])}" if len(mp) >= 2 else ""
            lines.append(f'> "{feedback}"')
            lines.append(
                f"> -- *{q.get('archetype_label', 'Unknown')}* (sentiment: {q.get('sentiment', '?')}/5{model_note})"
            )
            lines.append("")

    if stats["quotes_negative"]:
        lines.append("### Most Critical")
        lines.append("")
        for q in stats["quotes_negative"]:
            feedback = q.get("feedback")
            if not feedback:
                continue  # a response is only guaranteed to carry 'sentiment'
            mp = q.get("_model", "").split(".")
            model_note = f" via {'.'.join(mp[-2:])}" if len(mp) >= 2 else ""
            lines.append(f'> "{feedback}"')
            lines.append(
                f"> -- *{q.get('archetype_label', 'Unknown')}* (sentiment: {q.get('sentiment', '?')}/5{model_note})"
            )
            lines.append("")

    return "\n".join(lines)


def generate_report(
    responses: list[dict[str, Any]],
    run_dir: Path,
    feature_text: str | None = None,
) -> Path:
    """Compute stats and write the markdown report. Returns the report path."""
    if feature_text is None:
        feature_path = run_dir / "feature.txt"
        if feature_path.exists():
            feature_text = feature_path.read_text(encoding="utf-8")

    stats = compute_stats(responses)
    report = render_report(stats, feature_text)

    report_path = run_dir / "feedback_report.md"
    report_path.write_text(report, encoding="utf-8")

    stats_path = run_dir / "stats.json"
    serializable_stats = {
        k: v
        for k, v in stats.items()
        if k not in ("quotes_positive", "quotes_negative", "by_archetype")
    }
    stats_path.write_text(
        json.dumps(serializable_stats, indent=2, default=str), encoding="utf-8"
    )

    return report_path


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Aggregate customer feedback responses into a report."
    )
    parser.add_argument(
        "--input", type=str, required=True, help="Path to raw_responses.json"
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: {input_path} not found")
        sys.exit(1)

    responses = json.loads(input_path.read_text(encoding="utf-8"))
    run_dir = input_path.parent

    report_path = generate_report(responses, run_dir)
    print(f"Report generated → {report_path}")


if __name__ == "__main__":
    main()
