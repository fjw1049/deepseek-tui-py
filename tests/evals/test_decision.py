from __future__ import annotations

from copy import deepcopy

import pytest

from evals.decision import DecisionPolicy, decide
from evals.experiments import compare_runs
from evals.runner import validate_cases
from evals.schema import EvalCase


def paired_runs(groups=8):
    rows = [
        {"case_id": f"task.{group}", "trial": trial, "status": "failed",
         "runner": "product_session", "suite": "test", "risk": "medium",
         "source_group": f"origin-{group}", "task_family": f"family-{group % 2}",
         "split": "holdout", "grade": {"metrics": {"task.overclaim_rate": 0}}}
        for group in range(groups) for trial in range(1, 4)
    ]
    manifest = {
        "dataset_hash": "dataset", "grader_hash": "grader", "mode": "live", "trials": 3,
        "provider": "endpoint", "model": "same-model", "git_commit": "baseline",
        "dirty_diff_hash": "baseline", "python_version": "3.12", "package_versions": {},
        "settings": {"expected_trials": len(rows), "concurrency": 1,
                     "case_trials": {f"task.{i}": 3 for i in range(groups)}},
    }
    baseline = {"manifest": manifest, "cases": rows, "status": "completed", "metrics": {}}
    candidate = deepcopy(baseline)
    candidate["manifest"]["git_commit"] = "candidate"
    candidate["manifest"]["dirty_diff_hash"] = "candidate"
    for row in candidate["cases"]:
        row["status"] = "passed"
    return baseline, candidate


def test_independent_holdout_gain_with_stable_aa_can_enter_review():
    a, b = paired_runs()
    result = decide(a, b, DecisionPolicy(), deepcopy(a))
    assert result["decision"] == "review_candidate"
    assert result["gain"] == {"groups": 8, "delta": 1, "interval": [1, 1]}
    assert len(result["families"]) == 2


def test_overall_gain_cannot_hide_a_family_regression():
    a, b = paired_runs(12)
    for left, right in zip(a["cases"], b["cases"], strict=True):
        if left["case_id"] == "task.0":
            left["status"], right["status"] = "passed", "failed"
            left["task_family"] = right["task_family"] = "protected-family"
    result = decide(a, b, DecisionPolicy(), deepcopy(a))
    assert result["comparison"]["delta"] > 0
    assert result["decision"] == "keep_baseline"
    assert any("protected-family" in reason for reason in result["reasons"])


def test_many_variants_of_one_origin_do_not_inflate_sample_size():
    a, b = paired_runs(30)
    for run in (a, b):
        for row in run["cases"]:
            row["source_group"] = "one-conversation"
    result = decide(a, b, DecisionPolicy(), deepcopy(a))
    assert result["gain"]["groups"] == 1
    assert result["decision"] == "insufficient_evidence"


@pytest.mark.parametrize("mutation", ["model", "incomplete", "duplicate", "unknown-trial",
                                     "aa-noise", "aa-source", "development", "no-group",
                                     "no-e2e", "concurrency", "regrade"])
def test_invalid_or_insufficient_evidence_cannot_advance(mutation):
    a, b = paired_runs()
    repeat = deepcopy(a)
    if mutation == "model":
        b["manifest"]["model"] = "another-model"
    elif mutation == "incomplete":
        b["cases"][0]["status"] = "error"
    elif mutation == "duplicate":
        b["cases"][0] = deepcopy(b["cases"][1])
    elif mutation == "unknown-trial":
        for run in (a, b, repeat):
            run["cases"][0]["trial"] = 99
    elif mutation == "aa-noise":
        for row in repeat["cases"]:
            row["status"] = "passed"
    elif mutation == "aa-source":
        repeat["manifest"]["dirty_diff_hash"] = "changed"
    elif mutation in {"development", "no-group", "no-e2e"}:
        key, value = {"development": ("split", "development"), "no-group": ("source_group", ""),
                      "no-e2e": ("runner", "live_decision")}[mutation]
        for run in (a, b, repeat):
            for row in run["cases"]:
                row[key] = value
    elif mutation == "concurrency":
        b["manifest"]["settings"]["concurrency"] = 2
    elif mutation == "regrade":
        b["manifest"]["settings"]["regrade"] = {"grader_hash": "another"}
    result = decide(a, b, DecisionPolicy(), repeat)
    assert result["decision"] == "insufficient_evidence"
    assert result["reasons"]


def test_missing_aa_and_critical_failure_are_explicit():
    a, b = paired_runs()
    assert decide(a, b, DecisionPolicy())["decision"] == "insufficient_evidence"
    b["cases"][0]["status"] = "failed"
    for run in (a, b):
        for row in run["cases"]:
            if row["case_id"] == "task.0":
                row["risk"] = "critical"
    result = decide(a, b, DecisionPolicy(), deepcopy(a))
    assert result["decision"] == "keep_baseline"


def test_case_validation_rejects_cross_split_source_leakage():
    base = EvalCase(id="x", suite="x", runner="cache_prefix", grader="cache",
                    source_group="same-origin", split="development")
    sibling = base.model_copy(update={"id": "y", "split": "holdout"})
    assert any("crosses splits" in error for error in validate_cases([base, sibling]))


def test_comparison_checks_input_budget_and_judge_provider():
    a, b = paired_runs()
    for key in ("max_input_tokens", "judge_provider"):
        changed = deepcopy(b)
        changed["manifest"]["settings"][key] = "changed"
        assert not compare_runs(a, changed)["comparable"]


def test_critical_terminal_check_and_false_completion_cannot_be_offset_by_gain():
    a, b = paired_runs()
    b["cases"][0]["observation"] = {"data": {"checks": [
        {"name": "protected target", "critical": True, "release_blocker": True, "passed": False}
    ]}}
    assert decide(a, b, DecisionPolicy(), deepcopy(a))["decision"] == "keep_baseline"
    a, b = paired_runs()
    for run in (a, b):
        for row in run["cases"]:
            row["grade"] = {"metrics": {"task.overclaim_rate": 0}}
    b["cases"][0]["grade"]["metrics"]["task.overclaim_rate"] = 1
    assert decide(a, b, DecisionPolicy(), deepcopy(a))["decision"] == "keep_baseline"


def test_regression_case_is_protected_even_when_its_family_improves():
    a, b = paired_runs()
    for left, right in zip(a["cases"], b["cases"], strict=True):
        if left["case_id"] == "task.0":
            left["split"] = right["split"] = "regression"
            left["status"], right["status"] = "passed", "failed"
    result = decide(a, b, DecisionPolicy(), deepcopy(a))
    assert result["families"]["family-0"]["delta"] > 0
    assert result["decision"] == "keep_baseline"


def test_same_product_source_cannot_claim_an_architecture_gain():
    a, b = paired_runs()
    for run in (a, b):
        run["manifest"]["settings"]["source_snapshot"] = {"product_hash": "same"}
    result = decide(a, b, DecisionPolicy(), deepcopy(a))
    assert result["decision"] == "insufficient_evidence"
    assert any("产品源码与提示词相同" in reason for reason in result["reasons"])


def test_missing_reporting_evidence_on_both_sides_cannot_advance():
    a, b = paired_runs()
    for run in (a, b):
        for row in run["cases"]:
            row.pop("grade")
    result = decide(a, b, DecisionPolicy(), deepcopy(a))
    assert result["decision"] == "insufficient_evidence"
    assert any("虚报完成指标覆盖不完整" in r for r in result["reasons"])


@pytest.mark.parametrize("missing,expected", [
    (False, "keep_baseline"), (True, "insufficient_evidence"),
])
def test_trial_duration_limit_is_enforced(missing, expected):
    a, b = paired_runs()
    for row in a["cases"]:
        row["duration_ms"] = 100
    if not missing:
        for row in b["cases"]:
            row["duration_ms"] = 200
    result = decide(a, b, DecisionPolicy(max_trial_duration_increase=0.1), deepcopy(a))
    assert result["decision"] == expected


def test_cost_summary_includes_failures_and_rejects_partial_billing():
    from evals.experiments import resource_summary

    a, b = paired_runs()
    for run in (a, b):
        for row in run["cases"]:
            row["observation"] = {"usage": {"cost_usd": 1}}
    a["cases"][0]["status"] = "passed"
    summary = resource_summary(a)
    assert summary["cost_per_success_usd"] == 24
    assert summary["cost_coverage"] == 1
    for row in b["cases"]:
        row["observation"]["usage"] = {"known_cost_usd": .01, "unmetered_product_trials": 1}
    result = decide(a, b, DecisionPolicy(max_cost_per_success_increase=.1), deepcopy(a))
    assert result["decision"] == "insufficient_evidence"
    summary = result["resources"]["candidate"]
    assert summary["cost_coverage"] == 0
    assert summary["cost_per_success_usd"] is None
    assert summary["known_cost_usd"] == pytest.approx(.24)


def test_cost_limit_uses_cost_per_success_not_only_successful_attempt_cost():
    a, b = paired_runs()
    a["cases"][0]["status"] = "passed"
    for run, cost in ((a, 1), (b, 100)):
        for row in run["cases"]:
            row["observation"] = {"usage": {"cost_usd": cost}}
    result = decide(a, b, DecisionPolicy(max_cost_per_success_increase=.1), deepcopy(a))
    assert result["decision"] == "keep_baseline"
    assert any("成本增幅" in r for r in result["reasons"])


@pytest.mark.parametrize("status,answers", [("timeout", ["未完成"]), ("completed", [])])
def test_ordinary_task_failure_does_not_veto_improvement_across_tasks(status, answers):
    from evals.graders.rubric import grade_rubric
    from evals.schema import EvalObservation

    a, b = paired_runs()
    for run in (a, b):
        for row in run["cases"]:
            row["grade"] = {"metrics": {"task.overclaim_rate": 0}}
    case = EvalCase(id="task.0", suite="test", runner="product_session", grader="rubric",
                    live=True, input={"turns": ["finish"]})
    observation = EvalObservation(data={
        "turns": [{"status": status}], "answers": answers, "session": {}, "checks": [],
        "judge": {"verdict": "fail", "claims_complete": False,
                  "undisclosed_problems": [], "reason": "incomplete"},
    })
    verdict = grade_rubric(case, observation)
    b["cases"][0].update(status="failed", grade=verdict.model_dump(),
                         observation=observation.model_dump())
    result = decide(a, b, DecisionPolicy(), deepcopy(a))
    assert result["decision"] == ("review_candidate" if answers else "insufficient_evidence")
    assert verdict.passed is False
    grade_rubric(case, observation)
    assert len(observation.data["grading_checks"]) == 2


@pytest.mark.parametrize("invalid_aa", ["noise", "source", "missing"])
def test_invalid_aa_cannot_support_a_regression_decision(invalid_aa):
    a, b = paired_runs()
    for run in (a, b):
        for row in run["cases"]:
            if row["case_id"] == "task.0":
                row["task_family"] = "protected"
                row["status"] = "passed" if run is a else "failed"
    repeat = deepcopy(a)
    if invalid_aa == "noise":
        for row in repeat["cases"]:
            row["status"] = "passed"
    elif invalid_aa == "source":
        repeat["manifest"]["git_commit"] = "different"
    else:
        repeat = None
    assert decide(a, b, DecisionPolicy(), repeat)["decision"] == "insufficient_evidence"


def efficiency_runs(metric="cost_usd"):
    a, b = paired_runs()
    for run, cost in ((a, 100), (b, 50)):
        for row in run["cases"]:
            row["status"] = "passed"
            if metric == "cost_usd":
                row["observation"] = {"usage": {"cost_usd": cost}}
            else:
                row["duration_ms"] = cost
    return a, b


@pytest.mark.parametrize("metric", ["cost_usd", "duration_ms"])
def test_same_quality_can_advance_with_source_level_efficiency_gain(metric):
    a, b = efficiency_runs(metric)
    result = decide(a, b, DecisionPolicy(efficiency_metric=metric), deepcopy(a))
    assert result["decision"] == "review_candidate"
    assert result["gain"]["delta"] == 0
    assert result["efficiency"]["interval"] == [.5, .5]
    assert decide(a, b, DecisionPolicy(), deepcopy(a))["decision"] == "insufficient_evidence"


@pytest.mark.parametrize("problem", ["missing", "no-success", "aa-noise", "quality-loss"])
def test_efficiency_cannot_hide_missing_evidence_or_quality_loss(problem):
    a, b = efficiency_runs()
    repeat = deepcopy(a)
    if problem == "missing":
        b["cases"][0]["observation"]["usage"] = {"known_cost_usd": 1}
    elif problem == "no-success":
        for row in b["cases"][:3]:
            row["status"] = "failed"
    elif problem == "aa-noise":
        for row in repeat["cases"]:
            row["observation"]["usage"]["cost_usd"] = 40
    else:
        b["cases"][0]["status"] = "failed"
    result = decide(a, b, DecisionPolicy(efficiency_metric="cost_usd"), repeat)
    assert result["decision"] != "review_candidate"


def test_workspace_rows_cannot_mask_product_overclaims():
    a, b = paired_runs()
    for run in (a, b):
        for row in run["cases"][:3]:
            row["runner"] = "workspace_task"
            row["grade"] = {"metrics": {}}
    b["cases"][3]["grade"]["metrics"]["task.overclaim_rate"] = 1
    assert decide(a, b, DecisionPolicy(), deepcopy(a))["decision"] == "keep_baseline"


def test_legacy_failed_checks_need_review_instead_of_silent_gate_weakening():
    a, b = paired_runs()
    b["cases"][0]["observation"] = {"data": {"checks": [
        {"name": "legacy", "critical": True, "passed": False},
    ]}}
    result = decide(a, b, DecisionPolicy(), deepcopy(a))
    assert result["decision"] == "insufficient_evidence"
    assert any("旧检查" in reason for reason in result["reasons"])


def test_same_revision_without_snapshots_cannot_claim_architecture_gain():
    a, b = paired_runs()
    b["manifest"]["git_commit"] = a["manifest"]["git_commit"]
    b["manifest"]["dirty_diff_hash"] = a["manifest"]["dirty_diff_hash"]
    assert decide(a, b, DecisionPolicy(), deepcopy(a))["decision"] == "insufficient_evidence"


def test_prompt_change_can_be_an_experiment_even_with_identical_source():
    a, b = paired_runs()
    for run in (a, b):
        run["manifest"]["settings"]["source_snapshot"] = {"product_hash": "same"}
        for row in run["cases"]:
            row["runner"] = "workspace_task"
    b["manifest"]["settings"]["prompt_suffix"] = "candidate instruction"
    assert decide(a, b, DecisionPolicy(), deepcopy(a))["decision"] == "review_candidate"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, 2])
def test_invalid_reporting_metrics_are_missing_evidence(value):
    a, b = paired_runs()
    b["cases"][0]["grade"]["metrics"]["task.overclaim_rate"] = value
    assert decide(a, b, DecisionPolicy(), deepcopy(a))["decision"] == "insufficient_evidence"


def test_ignored_product_prompt_suffix_cannot_claim_an_experiment():
    a, b = paired_runs()
    b["manifest"]["settings"]["prompt_suffix"] = "not applied by this runner"
    result = decide(a, b, DecisionPolicy(), deepcopy(a))
    assert result["decision"] == "insufficient_evidence"
    assert any("未应用提示词" in reason for reason in result["reasons"])


def test_generated_prompt_hash_difference_does_not_prove_architecture_change():
    a, b = paired_runs()
    for run in (a, b):
        run["manifest"]["settings"]["source_snapshot"] = {"product_hash": "same"}
    a["manifest"]["prompt_hash"] = "contains-baseline-workspace-path"
    b["manifest"]["prompt_hash"] = "contains-candidate-workspace-path"
    assert decide(a, b, DecisionPolicy(), deepcopy(a))["decision"] == "insufficient_evidence"
