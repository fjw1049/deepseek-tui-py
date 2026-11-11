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
         "split": "holdout"}
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
        {"name": "protected target", "critical": True, "passed": False}
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
    assert any("产品源码相同" in reason for reason in result["reasons"])
