"""Work from saved sessions: score a finished run again, or summarize an archive."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.graders import grade
from evals.harness import HarnessContext
from evals.harness.product import grade_session
from evals.report import append_result, summarize, write_json
from evals.runner import REPO_ROOT, dataset_hash, grader_hash, load_cases
from evals.schema import RunSummary, TrialResult
from evals.session_metrics import aggregate, load_sessions, session_metrics


async def regrade(
    run: Path, judge_provider: str | None, judge_model: str | None, max_requests: int,
    *, reuse_judge: bool = False,
) -> tuple[Path, RunSummary]:
    """Same sessions, current checks and reviewer: a rubric fix needs no new agent runs."""
    cases = {case.id: case for case in load_cases()}
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    output = run / f"regrade-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')}"
    output.mkdir(parents=True, exist_ok=False)
    context = HarnessContext(
        workspace=str(REPO_ROOT),
        provider=manifest.get("provider"),
        model=manifest.get("model"),
        remaining_live_requests=max_requests,
        judge_provider=judge_provider or manifest.get("settings", {}).get("judge_provider"),
        judge_model=judge_model or manifest.get("settings", {}).get("judge_model"),
        artifacts_dir=output,
    )
    results: list[TrialResult] = []
    for line in (run / "cases.jsonl").read_text(encoding="utf-8").splitlines():
        original = TrialResult.model_validate_json(line)
        observation = original.observation
        if observation is None or "session_dir" not in observation.data:
            continue
        before = context.fork()
        try:
            case = cases[original.case_id]
            session_dir = run / "sessions" / observation.data["session_dir"]
            turns = json.loads((session_dir / "turns.json").read_text(encoding="utf-8"))
            saved = observation.data.get("judge") if reuse_judge else None
            if reuse_judge and not saved:
                raise ValueError("reuse-judge requested but saved judge evidence is missing")
            fresh = await grade_session(case, session_dir, turns, context, saved_judge=saved)
            if "trial_isolation" in observation.data:
                fresh.data["trial_isolation"] = observation.data["trial_isolation"]
            verdict = grade(case, fresh)
            result = original.model_copy(update={
                "status": "passed" if verdict.passed else "failed",
                "grade": verdict, "observation": fresh, "error": None,
            })
        except Exception as exc:
            result = original.model_copy(deep=True, update={
                "status": "error", "grade": None,
                "error": f"regrade: {type(exc).__name__}: {exc}",
            })
        assert result.observation is not None
        usage = dict(observation.usage)
        extra_requests = context.requests - before.requests
        extra_priced = context.priced_requests - before.priced_requests
        extra_cost = context.cost_usd - before.cost_usd
        for key, value in context.usage.items():
            usage[key] = usage.get(key, 0) + value - before.usage.get(key, 0)
        for key, value in {
            "requests": extra_requests, "review_requests": extra_requests,
            "metered_requests": context.metered_requests - before.metered_requests,
            "priced_requests": extra_priced, "known_cost_usd": extra_cost,
        }.items():
            usage[key] = usage.get(key, 0) + value
        if "cost_usd" in usage and extra_requests == extra_priced:
            usage["cost_usd"] += extra_cost
        else:
            usage.pop("cost_usd", None)
        usage["regrade_requests"] = extra_requests
        result.observation.usage = usage
        results.append(result)
        append_result(output / "cases.jsonl", result)
    summary = summarize(manifest["run_id"], results)
    reviewed_ids = {result.case_id for result in results}
    review_metadata = {
        "reuse_judge": reuse_judge,
        "grader_hash": grader_hash(),
        "dataset_hash": dataset_hash([case for key, case in cases.items() if key in reviewed_ids]),
        "judge_provider": judge_provider or manifest.get("settings", {}).get("judge_provider")
        or manifest.get("provider"),
        "judge_model": judge_model or manifest.get("settings", {}).get("judge_model")
        or manifest.get("model"),
    }
    write_json(output / "manifest.json", {**manifest, "settings": {
        **manifest.get("settings", {}), "regrade": review_metadata,
    }})
    write_json(output / "summary.json", summary.model_dump(mode="json"))
    from evals.scorecard import write_scorecard

    write_scorecard(output)
    return output, summary


def soak_baseline(store: Path, output: Path, exclude: Path | None) -> dict[str, Any]:
    """Run-level facts for an archived store. These describe runs, not correctness."""
    skipped = set(json.loads(exclude.read_text(encoding="utf-8"))) if exclude else set()
    rows = [
        session_metrics(session)
        for session in load_sessions(store)
        if session.thread_id not in skipped
    ]
    report = {"sessions": len(rows), "metrics": aggregate(rows)}
    write_json(output, report)
    return report
