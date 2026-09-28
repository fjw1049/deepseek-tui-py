"""Protocol and presentation boundary regressions from audit 14."""

import pytest
from pydantic import ValidationError

from deepseek_tui.engine.events import AgentRoundCompleteEvent
from deepseek_tui.presentation.reducer import TurnPresentationReducer
from deepseek_tui.presentation.semantics import (
    BatchKind,
    batch_intent_text,
    batch_root,
    classify_batch,
)
from deepseek_tui.protocol.events import McpStartupStatus
from deepseek_tui.protocol.messages import ImageBlock, MessageRequest
from deepseek_tui.protocol.responses import ToolCall, Usage


@pytest.mark.parametrize("crop", [(0, 0, 0, 0), (0, 0, -1, 2), (-1, 0, 2, 2), (0, -1, 2, 2)])
def test_reject_invalid_crop(crop):
    with pytest.raises(ValidationError):
        ImageBlock(
            asset_id="a" * 64, mime_type="image/png", width=10, height=10, byte_size=1, crop=crop
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"model": ""},
        {"model": "  "},
        {"max_tokens": 0},
        {"max_tokens": -1},
        {"temperature": float("nan")},
        {"top_p": float("inf")},
    ],
)
def test_invalid_request_rejected(kwargs):
    with pytest.raises(ValidationError):
        MessageRequest(**{"model": "provider-model", **kwargs})


@pytest.mark.parametrize(
    "key",
    [
        "input_tokens",
        "output_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
        "reasoning_tokens",
        "prompt_tokens",
        "completion_tokens",
        "prompt_cache_hit_tokens",
        "prompt_cache_miss_tokens",
    ],
)
def test_negative_usage_rejected(key):
    with pytest.raises(ValidationError):
        Usage.model_validate({key: -1})


def test_failed_wrapper_cannot_become_ready():
    value = McpStartupStatus.model_validate({"failed": {"type": "ready", "error": "broken"}})
    assert value.model_dump() == {"failed": {"error": "broken"}}


def round_event(index=0, ids=("a", "b")):
    return AgentRoundCompleteEvent(index, tuple(ToolCall(id=i, name="read_file") for i in ids))


def test_repeated_round_preserves_partial_and_completed_results():
    reducer = TurnPresentationReducer()
    batch = reducer.on_round_complete(round_event())
    reducer.on_tool_result("a", success=True)
    assert reducer.on_round_complete(round_event()) is batch
    assert reducer.round_count == 1
    assert reducer.on_tool_result("b", success=True) is batch
    assert reducer.on_round_complete(round_event()) is batch
    assert reducer.on_tool_result("b", success=False) is None
    assert batch.status == "done"


def test_conflicting_and_overlapping_rounds_do_not_modify_state():
    reducer = TurnPresentationReducer()
    batch = reducer.on_round_complete(round_event())
    for event in (round_event(0, ("c",)), round_event(1, ("c",))):
        with pytest.raises(ValueError):
            reducer.on_round_complete(event)
    assert reducer.on_turn_cancelled() is batch
    assert batch.is_terminal
    assert not batch.all_results_received
    assert reducer.on_tool_result("a", success=True) is None
    assert not batch.receive_terminal("a", status="done")
    assert not reducer._batch_by_tool_id
    reducer.reset()
    assert reducer.on_round_complete(round_event()).status == "running"


@pytest.mark.parametrize("command", ["cat README.md", "pytest -q", "touch output.txt"])
def test_shell_display_is_neutral(command):
    tools = [ToolCall(id="a", name="exec_shell", arguments={"command": command})]
    assert classify_batch(tools) == BatchKind.COMMAND
    assert batch_intent_text(classify_batch(tools), tools) == "执行命令"


@pytest.mark.parametrize(
    "path", ["/Users/example/project/src", r"C:\Users\example\project\src", "src/components"]
)
def test_batch_root_does_not_claim_filesystem_root(path):
    assert batch_root(
        [ToolCall(id="a", name="list_dir", arguments={"path": path})]
    ) == path.replace("\\", "/")


@pytest.mark.parametrize(
    "payload", ["ready", "starting", "cancelled", {"failed": {"error": "broken"}}]
)
def test_startup_status_legacy_roundtrip(payload):
    assert McpStartupStatus.model_validate(payload).model_dump() == payload


def test_valid_crop_request_and_usage_aliases():
    image = ImageBlock(
        asset_id="a" * 64,
        mime_type="image/png",
        width=10,
        height=10,
        byte_size=1,
        crop=(9, 9, 1, 1),
    )
    assert ImageBlock.model_validate_json(image.model_dump_json()) == image
    assert MessageRequest(model="custom-model", max_tokens=1).max_tokens == 1
    usage = Usage.model_validate(
        {"prompt_tokens": 10, "completion_tokens": 2, "prompt_tokens_details": {"cached_tokens": 4}}
    )
    assert usage.input_tokens == 10
    assert usage.cache_read_input_tokens == 4
    assert Usage.model_validate_json(usage.model_dump_json()) == usage


def test_nested_negative_usage_rejected():
    with pytest.raises(ValidationError):
        Usage.model_validate({"prompt_tokens": 10, "prompt_tokens_details": {"cached_tokens": -1}})


def test_duplicate_ids_rejected_before_reducer_mutation():
    reducer = TurnPresentationReducer()
    with pytest.raises(ValueError):
        reducer.on_round_complete(round_event(ids=("a", "a")))
    assert reducer.round_count == 0
    assert not reducer._batch_by_tool_id
    assert reducer.on_round_complete(round_event()) is not None


def test_changed_arguments_conflict_even_if_producer_mutates_original():
    reducer = TurnPresentationReducer()
    event = AgentRoundCompleteEvent(
        0, (ToolCall(id="a", name="read_file", arguments={"path": "old"}),)
    )
    batch = reducer.on_round_complete(event)
    event.tool_calls[0].arguments["path"] = "new"
    with pytest.raises(ValueError):
        reducer.on_round_complete(event)
    assert batch.status == "running"
    reducer.on_turn_cancelled()
    with pytest.raises(ValueError):
        reducer.on_round_complete(round_event(index=1))


def test_large_mixed_result_batch_completion_and_duplicate_handling():
    reducer = TurnPresentationReducer()
    ids = tuple(str(i) for i in range(2048))
    batch = reducer.on_round_complete(round_event(ids=ids))
    for index, tool_id in enumerate(ids):
        terminal = reducer.on_tool_result(tool_id, success=index % 2 == 0)
        assert (terminal is batch) == (index == len(ids) - 1)
        assert reducer.on_tool_result(tool_id, success=True) is None
    assert batch.is_terminal and batch.all_results_received
    assert batch.status == "partial_fail"
    assert len(batch.completed_ids) == len(batch.failed_ids) == 1024
    assert not reducer._batch_by_tool_id
