"""Summarize real product A/B trials, including failed compression attempts.

Usage: python -m evals.compression_compare BASELINE CANDIDATE OUTPUT.json
Costs are normalized to the official off-peak Flash USD rates checked
2026-11-12; this is a token-based estimate, not a provider invoice.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from evals.session_metrics import _tool, load_sessions

PRICES = {"hit": 0.003, "miss": 0.15, "output": 0.6}


def summarize(directory: Path) -> dict:
    rows = []
    results = directory / "cases.jsonl"
    if not results.exists():
        return {"cases": [], "totals": {}}
    for line in results.read_text().splitlines():
        result = json.loads(line)
        data = (result.get("observation") or {}).get("data", {})
        grade = result.get("grade") or {}
        usage = Counter()
        compressions = Counter()
        sources = Counter()
        tool_names = Counter()
        tool_errors = []
        tool_sequence = []
        for session in (directory / "sessions").glob(result["case_id"] + "-*"):
            for trace in load_sessions(session):
                for item in trace.items:
                    name, arguments = _tool(item)
                    if not name:
                        continue
                    tool_names[name] += 1
                    evidence = {
                        "item_id": item["id"],
                        "tool": name,
                        "status": item["status"],
                        "arguments": arguments,
                        "result_excerpt": (item.get("detail") or "")[:1000],
                    }
                    tool_sequence.append(evidence)
                    if item["status"] == "failed":
                        tool_errors.append(evidence)
            for turn in (session / "turns").glob("*.json"):
                record = json.loads(turn.read_text())
                metered = record.get("usage") or {}
                for key in (
                    "input_tokens",
                    "output_tokens",
                    "cache_hit_tokens",
                    "cache_miss_tokens",
                ):
                    usage[key] += metered.get(key, 0)
                sources.update(metered.get("sources") or {})
            for events in (session / "events").glob("*.jsonl"):
                for event_line in events.read_text().splitlines():
                    event = json.loads(event_line)
                    payload = event.get("payload") or {}
                    if (
                        event.get("event") == "harness.intervention"
                        and payload.get("kind") == "compaction"
                    ):
                        compressions[payload["outcome"]] += 1
        cost = (
            usage["cache_hit_tokens"] * PRICES["hit"]
            + usage["cache_miss_tokens"] * PRICES["miss"]
            + usage["output_tokens"] * PRICES["output"]
        ) / 1e6
        rows.append(
            {
                "case_id": result["case_id"],
                "status": result["status"],
                "score": grade.get("score"),
                "usage": dict(usage),
                "cost_usd_estimate": cost,
                "compressions": dict(compressions),
                "request_sources": dict(sources),
                "tool_counts": dict(tool_names),
                "tool_errors": tool_errors,
                "tool_sequence": tool_sequence,
                "session_metrics": data.get("session", {}),
                "answers": data.get("answers", []),
                "checks": data.get("checks", []),
                "turns": data.get("turns", []),
                "judge": data.get("judge"),
                "error": result.get("error"),
            }
        )
    scored = [r for r in rows if r["score"] is not None]
    return {
        "cases": rows,
        "totals": {
            "cases": len(rows),
            "passed": sum(r["status"] == "passed" for r in rows),
            "mean_score": sum(r["score"] for r in scored) / len(scored) if scored else None,
            "cost_usd_estimate": sum(r["cost_usd_estimate"] for r in rows),
            "successful_compressions": sum(r["compressions"].get("compacted", 0) for r in rows),
            "cases_with_two_compressions": sum(
                r["compressions"].get("compacted", 0) >= 2 for r in rows
            ),
            "failed_compressions": sum(r["compressions"].get("failed", 0) for r in rows),
            "timed_out_cases": [
                r["case_id"] for r in rows if any(t.get("status") == "timeout" for t in r["turns"])
            ],
            "failed_checks": [
                f"{r['case_id']}: {c['name']}" for r in rows for c in r["checks"] if not c["passed"]
            ],
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--baseline-concurrency", type=int, default=3)
    parser.add_argument("--candidate-concurrency", type=int, default=10)
    parser.add_argument("--independent-checks", type=Path)
    args = parser.parse_args()
    report = {
        "model": "deepseek-flash",
        "trigger_tokens": 30000,
        "keep_recent_tokens": 2000,
        "concurrency": {
            "baseline": args.baseline_concurrency,
            "candidate": args.candidate_concurrency,
        },
        "price_basis": {
            "usd_per_million": PRICES,
            "source": "https://api-docs.deepseek.com/quick_start/pricing/",
            "checked_date": "2026-11-12",
            "period": "off-peak",
        },
        "baseline": summarize(args.baseline),
        "candidate": summarize(args.candidate),
        "limitations": [
            "One trial per task; no statistical claim of optimality.",
            (
                "Concurrency is matched; shared service load and cache availability may still vary."
                if args.baseline_concurrency == args.candidate_concurrency
                else "Concurrency differs; runtime and cache availability may vary."
            ),
            "Both arms lower the compression trigger; comparison isolates the summary algorithm.",
            "Cost excludes the separate evaluator judge and failed exploratory runs.",
            "150K/250K production thresholds and non-DeepSeek costs are not validated by this run.",
            "The 30K trigger is not a hard payload bound: "
            "pinned/recent history can prevent compression.",
            "A timed-out first turn prevents later user requests from being sent; "
            "missing follow-up work is not proof of summary information loss.",
            "Not every case undergoes 2-3 successful compressions; "
            "inspect per-case coverage before drawing conclusions.",
        ],
    }
    if args.independent_checks:
        report["independent_checks"] = json.loads(args.independent_checks.read_text())
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(
        json.dumps({k: report[k]["totals"] for k in ("baseline", "candidate")}, ensure_ascii=False)
    )


if __name__ == "__main__":
    main()
