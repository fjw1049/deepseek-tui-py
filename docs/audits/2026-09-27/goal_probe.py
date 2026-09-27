"""Offline audit 07 probes. Assertions characterize current boundaries, not acceptance."""

import json
import tempfile
import time
from pathlib import Path

from deepseek_tui.goal.commands import parse_goal_command
from deepseek_tui.goal.service import GoalService
from deepseek_tui.goal.workspace import workspace_digest


def complete(service):
    service.record_tool_result("pwd", "exec_shell", {"command": "pwd"}, success=True, output="/tmp")
    service.mark_complete(
        "All requirements met",
        evidence=["pwd"],
        audit={
            "checks": [
                {
                    "requirement_id": r["id"],
                    "explanation": "Claimed verified by pwd",
                    "evidence": ["pwd"],
                }
                for r in service.snapshot().requirements
            ]
        },
    )


def main():
    results = {}
    service = GoalService()
    service.create("Fix checkout and pass the regression tests")
    complete(service)
    results["semantic_coverage"] = service.snapshot().status.value
    snap = service.snapshot()
    snap.completion_audit["checks"][0]["explanation"] = "changed outside service"
    results["snapshot_alias_changes_state"] = (
        service.snapshot().completion_audit["checks"][0]["explanation"] == "changed outside service"
    )
    service = GoalService()
    service.create("first")
    service.enqueue("second")
    complete(service)
    dumped = service.dump()
    restored = GoalService()
    restored.restore(dumped.goal, dumped.queue)
    results["restore_completed_with_queue"] = {
        "status": restored.snapshot().status.value,
        "queued": len(restored.queue_items()),
        "promoted": restored.consume_promoted() is not None,
        "continues": restored.peek_continuation().should_continue,
    }
    errors = {}
    for label, raw in [
        ("unicode_digit", "next manage delete ²"),
        ("long_integer", "budget tokens " + "9" * 5000),
    ]:
        try:
            errors[label] = parse_goal_command(raw).kind
        except ValueError:
            errors[label] = "uncaught ValueError"
    results["parser"] = errors
    service = GoalService()
    service.create("many failed checks")
    for i in range(200):
        service.record_tool_result(str(i), "exec_shell", {"command": f"check {i}"}, success=False)
    results["evidence_count_after_200_unique_failures"] = len(service.snapshot().evidence)
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        path = root / "script.sh"
        path.write_text("#!/bin/sh\nexit 0\n")
        path.chmod(0o644)
        before = workspace_digest(root)
        path.chmod(0o755)
        results["chmod_changes_digest"] = workspace_digest(root) != before
        # Fixed 8MiB source corpus; direct calls, no model or actual task tools.
        for i in range(8):
            (root / f"{i}.txt").write_bytes(b"x" * (1024 * 1024))
        samples = []
        for _ in range(5):
            start = time.perf_counter()
            workspace_digest(root)
            samples.append((time.perf_counter() - start) * 1000)
        results["workspace_digest_8mib_median_ms"] = round(sorted(samples)[2], 3)
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
