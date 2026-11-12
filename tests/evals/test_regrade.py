import json

from evals.regrade import regrade
from evals.schema import EvalCase, EvalObservation, TrialResult


async def test_reuse_never_calls_missing_judge_and_preserves_per_case_errors(tmp_path, monkeypatch):
    cases = [EvalCase(id=name, suite="test", runner="product_session", grader="rubric",
                      input={"turns": ["交付"]}, expect={"rubric": ["有产物"]})
             for name in ("missing", "malformed", "good")]
    verdict = {
        "verdict": "pass", "claims_complete": True, "completion_claim_supported": True,
        "completion_claim_evidence": "产物支持完成声明", "undisclosed_problems": [],
        "reason": "交付完成", "criteria": [{"id": 1, "met": True, "evidence": "产物存在"}],
    }
    rows = []
    for case in cases:
        session = tmp_path / "sessions" / case.id
        session.mkdir(parents=True)
        (session / "turns.json").write_text('[{"status":"completed"}]')
        judge = {} if case.id == "missing" else {
            **verdict, "criteria": [] if case.id == "malformed" else verdict["criteria"],
        }
        obs = EvalObservation(
            usage={"cost_usd": .02, "known_cost_usd": .02, "requests": 2, "priced_requests": 2},
            data={"session_dir": case.id, "judge": judge},
        )
        rows.append(TrialResult(case_id=case.id, runner=case.runner, suite="test", risk="medium",
                                trial=1, status="error", error="old error", duration_ms=1,
                                observation=obs))
    (tmp_path / "manifest.json").write_text('{"run_id":"original"}')
    (tmp_path / "cases.jsonl").write_text("\n".join(r.model_dump_json() for r in rows))
    monkeypatch.setattr("evals.regrade.load_cases", lambda: cases)
    reviewed = []

    async def saved_only(case, session_dir, turns, context, *, saved_judge):
        assert saved_judge  # No missing review may reach the model-calling path.
        reviewed.append(case.id)
        return EvalObservation(data={"turns": turns, "answers": ["已交付"], "session": {},
                                     "checks": [], "judge": saved_judge, "session_dir": case.id})

    monkeypatch.setattr("evals.regrade.grade_session", saved_only)
    output, summary = await regrade(tmp_path, None, None, 0, reuse_judge=True)
    assert reviewed == ["malformed", "good"]
    assert summary.errors == 2 and summary.passed == 1
    saved = [json.loads(line) for line in (output / "cases.jsonl").read_text().splitlines()]
    assert [r["status"] for r in saved] == ["error", "error", "passed"]
    assert saved[-1]["error"] is None
    assert all(r["observation"]["usage"]["cost_usd"] == .02 for r in saved)
    assert all(r["observation"]["usage"]["regrade_requests"] == 0 for r in saved)
    assert all(r["grade"] is None for r in saved[:2])
    assert (output / "scorecard.md").is_file()
    assert (output / "manifest.json").is_file()
    second, _ = await regrade(tmp_path, None, None, 0, reuse_judge=True)
    assert second != output
