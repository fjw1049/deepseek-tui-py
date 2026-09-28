"""Audit 14: deterministic boundary probes and a small batch-state comparison.

Run: PYTHONPATH=src .venv/bin/python docs/audits/2026-09-27/presentation_probe.py
This records current behavior; it is not a desired-behavior regression suite.
"""

from __future__ import annotations

import json
import statistics
import time
from pathlib import Path

from deepseek_tui.engine.events import AgentRoundCompleteEvent
from deepseek_tui.media import image_token_estimate
from deepseek_tui.presentation.models import ActionBatchView
from deepseek_tui.presentation.reducer import TurnPresentationReducer
from deepseek_tui.presentation.semantics import batch_root, classify_batch, template_narration
from deepseek_tui.protocol.events import McpStartupStatus
from deepseek_tui.protocol.messages import ImageBlock, MessageRequest
from deepseek_tui.protocol.responses import ToolCall, Usage


def batch(ids):
    return ActionBatchView(0, tuple(ids), "explore", None, "test", "mixed")


class SetPrototype:
    """Throwaway alternative: cached expected IDs and incremental terminal membership."""

    def __init__(self, ids):
        self.expected = set(ids)
        self.finished = set()
        self.status = "running"
        self.has_error = False

    def receive_terminal(self, tool_call_id, *, status):
        if tool_call_id not in self.expected or tool_call_id in self.finished:
            return False
        self.finished.add(tool_call_id)
        self.has_error |= status != "done"
        if self.finished != self.expected:
            return False
        self.status = "partial_fail" if self.has_error else "done"
        return True


def run():
    results = {}
    reducer = TurnPresentationReducer()
    event = AgentRoundCompleteEvent(
        0, (ToolCall(id="a", name="read_file"), ToolCall(id="b", name="read_file"))
    )
    original = reducer.on_round_complete(event)
    reducer.on_tool_result("a", success=True)
    replay = reducer.on_round_complete(event)
    reducer.on_tool_result("b", success=True)
    results["duplicate_round"] = {
        "same_batch": original is replay,
        "round_count": reducer.round_count,
        "status": replay.status,
        "completed_ids": sorted(replay.completed_ids),
    }
    reducer = TurnPresentationReducer()
    old = reducer.on_round_complete(
        AgentRoundCompleteEvent(0, (ToolCall(id="old", name="read_file"),))
    )
    current = reducer.on_round_complete(
        AgentRoundCompleteEvent(1, (ToolCall(id="new", name="read_file"),))
    )
    reducer.on_turn_cancelled()
    results["overlap_cancel"] = {
        "older_status": old.status,
        "current_status": current.status,
        "retained_tool_ids": sorted(reducer._batch_by_tool_id),
    }
    results["cancel_terminal"] = {"status": current.status, "is_terminal": current.is_terminal}
    for name, command in [
        ("read", "cat README.md"),
        ("verify", "pytest -q"),
        ("write", "touch output.txt"),
    ]:
        tools = [ToolCall(id="shell", name="exec_shell", arguments={"command": command})]
        kind = classify_batch(tools)
        results[f"shell_{name}"] = {
            "kind": kind.value,
            "narration": template_narration(locale="zh", batch=kind, tool_calls=tools),
        }
    results["absolute_root"] = batch_root(
        [ToolCall(id="ls", name="list_dir", arguments={"path": "/Users/example/project/src"})]
    )
    block = ImageBlock(
        asset_id="a" * 64,
        mime_type="image/png",
        width=100,
        height=100,
        byte_size=1,
        crop=(0, 0, 0, 0),
    )
    try:
        image_token_estimate(block)
    except Exception as exc:
        results["zero_crop"] = type(exc).__name__
    results["invalid_request_accepted"] = MessageRequest(
        model="", max_tokens=-1, temperature=float("nan")
    ).model_dump(mode="json")
    results["invalid_request_accepted"]["temperature"] = "NaN (accepted float)"
    results["negative_usage"] = Usage(input_tokens=-10, output_tokens=-2).model_dump()
    results["failed_status_override"] = McpStartupStatus.model_validate(
        {"failed": {"error": "broken", "type": "ready"}}
    ).model_dump()
    # Round-trip known variants remains intact; preserve it when fixing coercion.
    results["status_roundtrips"] = all(
        McpStartupStatus.model_validate_json(v.model_dump_json()).model_dump() == v.model_dump()
        for v in [
            McpStartupStatus.starting(),
            McpStartupStatus.ready(),
            McpStartupStatus.cancelled(),
            McpStartupStatus.failed("error"),
        ]
    )
    actions = [("b", "done"), ("b", "failed"), ("unknown", "done"), ("a", "denied"), ("c", "done")]
    left, right = batch(("a", "b", "c")), SetPrototype(("a", "b", "c"))
    assert [left.receive_terminal(i, status=s) for i, s in actions] == [
        right.receive_terminal(i, status=s) for i, s in actions
    ]
    assert left.status == right.status == "partial_fail"
    timings = []
    for count in (16, 256, 2048):
        ids = [str(i) for i in range(count)]
        row = {"tools": count}
        for label, factory in [("current", batch), ("set_prototype", SetPrototype)]:
            samples = []
            for _ in range(7):
                state = factory(ids)
                start = time.perf_counter()
                for tool_id in reversed(ids):
                    state.receive_terminal(tool_id, status="done")
                samples.append((time.perf_counter() - start) * 1000)
            row[label + "_median_ms"] = round(statistics.median(samples), 4)
        timings.append(row)
    results["batch_benchmark"] = timings
    results["prototype_scope"] = (
        "Membership/completion only; excludes UI, schema, approval and rendering; no production replacement."
    )
    return results


if __name__ == "__main__":
    result = run()
    path = Path(__file__).with_name("presentation-probe-results.json")
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
