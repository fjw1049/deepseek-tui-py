"""Run with PYTHONPATH=src .venv/bin/python <this file>.

Compare the audit-14 membership algorithm with the repaired implementation.
Construction, declaration/deep-copy and UI rendering are excluded.
"""

from __future__ import annotations

import json
from pathlib import Path
from statistics import median
from time import perf_counter

from deepseek_tui.presentation.models import ActionBatchView


class LegacyBatch:
    """Pre-fix tuple membership and recomputed unions/expected sets."""

    def __init__(self, ids):
        self.expected_tool_ids = tuple(ids)
        self.completed_ids, self.failed_ids, self.denied_ids = set(), set(), set()
        self.has_error = False
        self.status = "running"

    @property
    def terminal_ids(self):
        return self.completed_ids | self.failed_ids | self.denied_ids

    def receive_terminal(self, tool_call_id, *, status):
        if tool_call_id not in self.expected_tool_ids or tool_call_id in self.terminal_ids:
            return False
        if status == "done":
            self.completed_ids.add(tool_call_id)
        elif status == "denied":
            self.denied_ids.add(tool_call_id)
            self.has_error = True
        else:
            self.failed_ids.add(tool_call_id)
            self.has_error = True
        if not (bool(self.expected_tool_ids) and self.terminal_ids >= set(self.expected_tool_ids)):
            return False
        self.status = "partial_fail" if self.has_error else "done"
        return True


def fixed(ids):
    return ActionBatchView(0, tuple(ids), "explore", None, "test", "mixed")


def run():
    actions = [("b", "done"), ("b", "failed"), ("unknown", "done"), ("a", "denied"), ("c", "done")]
    old, new = LegacyBatch(("a", "b", "c")), fixed(("a", "b", "c"))
    assert [old.receive_terminal(i, status=s) for i, s in actions] == [
        new.receive_terminal(i, status=s) for i, s in actions
    ]
    assert old.status == new.status == "partial_fail"
    rows = []
    for count in (16, 256, 2048):
        ids = tuple(str(i) for i in range(count))
        row = {"tools": count}
        for label, factory in [("legacy", LegacyBatch), ("fixed", fixed)]:
            samples = []
            for _ in range(7):
                batch = factory(ids)
                start = perf_counter()
                for tool_id in reversed(ids):
                    batch.receive_terminal(tool_id, status="done")
                samples.append(1000 * (perf_counter() - start))
                assert batch.status == "done"
            row[label + "_median_ms"] = round(median(samples), 4)
        rows.append(row)
    return {
        "scope": "membership/completion only; 7 repetitions, construction excluded",
        "mixed_results_equivalent": True,
        "timings": rows,
    }


if __name__ == "__main__":
    data = run()
    Path(__file__).with_name("presentation-fixed-probe-results.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(data, indent=2))
