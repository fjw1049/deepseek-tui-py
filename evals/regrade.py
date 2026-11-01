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
from evals.runner import REPO_ROOT, load_cases
from evals.schema import RunSummary, TrialResult
from evals.session_metrics import aggregate, load_sessions, session_metrics


async def regrade(
    run: Path, judge_provider: str | None, judge_model: str | None, max_requests: int,
    *, reuse_judge: bool = False,
) -> tuple[Path, RunSummary]:
    """Same sessions, current checks and reviewer: a rubric fix needs no new agent runs."""
    cases = {case.id: case for case in load_cases()}
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    output = run / f"regrade-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    context = HarnessContext(
        workspace=str(REPO_ROOT),
        provider=manifest.get("provider"),
        model=manifest.get("model"),
        remaining_live_requests=max_requests,
        judge_provider=judge_provider,
        judge_model=judge_model,
        artifacts_dir=output,
    )
    results: list[TrialResult] = []
    for line in (run / "cases.jsonl").read_text(encoding="utf-8").splitlines():
        original = TrialResult.model_validate_json(line)
        observation = original.observation
        if observation is None or "session_dir" not in observation.data:
            continue
        case = cases[original.case_id]
        session_dir = run / "sessions" / observation.data["session_dir"]
        turns = json.loads((session_dir / "turns.json").read_text(encoding="utf-8"))
        saved = observation.data.get("judge") if reuse_judge else None
        fresh = await grade_session(case, session_dir, turns, context, saved_judge=saved)
        fresh.usage = observation.usage
        verdict = grade(case, fresh)
        result = original.model_copy(
            update={
                "status": "passed" if verdict.passed else "failed",
                "grade": verdict,
                "observation": fresh,
            }
        )
        results.append(result)
        append_result(output / "cases.jsonl", result)
    summary = summarize(manifest["run_id"], results)
    write_json(output / "manifest.json", manifest)
    write_json(output / "summary.json", summary.model_dump(mode="json"))
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
