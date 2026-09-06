"""Compaction and cycle-state survival grader."""

from __future__ import annotations

import json

from evals.schema import EvalCase, EvalObservation, GradeResult


def grade_constraints(case: EvalCase, observation: EvalObservation) -> GradeResult:
    data = observation.data
    if "bridge_count" not in data and "assistant_text" not in data:
        raise ValueError("constraint evidence is missing")
    reasons: list[str] = []
    missing = list(data.get("missing_requests", []))
    if missing:
        reasons.append(f"lost user requests: {missing}")
    if "bridge_count" in data and int(data["bridge_count"]) != 1:
        reasons.append("compaction bridge was duplicated or lost")
    if "ledger_count" in data and int(data["ledger_count"]) != 1:
        reasons.append("request ledger was duplicated or lost")
    missing_state = list(data.get("missing_structured_state", []))
    if missing_state:
        reasons.append(f"lost structured state: {missing_state}")
    if data.get("summary_is_evidence") is True:
        reasons.append("compaction summary was treated as evidence")
    assistant_text = str(data.get("assistant_text", ""))
    required_terms = [str(term) for term in case.expect.get("required_response_terms", [])]
    missing_terms = [term for term in required_terms if term not in assistant_text]
    if missing_terms:
        reasons.append(f"response lost required constraints: {missing_terms}")
    if required_terms:
        # File names alone do not establish constraint meaning. Old term-only
        # live cases must migrate to an explicit, structured decision probe.
        raise ValueError("term-only constraint grading is unsupported; use response_json")
    if "response_json" in case.expect:
        try:
            actual = json.loads(
                assistant_text.strip()
                .removeprefix("```json")
                .removeprefix("```")
                .removesuffix("```")
                .strip()
            )
        except (ValueError, TypeError):
            actual = None
        if actual != case.expect["response_json"]:
            reasons.append("structured constraint decision differs from the expected restrictions")
    forbidden = set(case.expect.get("forbidden_tools", []))
    selected = set(data.get("tool_names", []))
    bad_tools = sorted(forbidden & selected)
    if bad_tools:
        reasons.append(f"constraint violation through tools: {bad_tools}")
    passed = not reasons
    expected = (
        len(case.input.get("user_requests", []))
        + len(case.input.get("structured_state_contains", []))
        + len(required_terms)
    )
    survived = expected - len(missing) - len(missing_state) - len(missing_terms)
    survival = 1.0 if expected == 0 else max(0.0, survived / expected)
    return GradeResult(
        passed=passed,
        score=survival if passed else min(survival, 0.99),
        metrics={"constraints.survival_rate": survival}
        if "bridge_count" in data
        else {
            "constraints.decision_pass_rate": float(passed),
        },
        reasons=reasons,
    )
