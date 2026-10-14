"""Bounded task authorization, unknown operation reconciliation and media provenance."""

import io
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from deepseek_tui.browser.service import (
    BrowserAction,
    BrowserActionError,
    BrowserRun,
    BrowserService,
)


@pytest.mark.parametrize(
    "changed",
    ["ref_only", "observation", "node", "record", "document", "generation", "task", "effect", "truncated"],
)
def test_task_approval_equivalence_never_expands_target_or_effect(tmp_path, changed):
    service = BrowserService(tmp_path)
    run = BrowserRun("t", tmp_path)
    service.runs["t"] = run
    run.latest_observation = {
        "observation_id": "old",
        "document_id": "doc",
        "elements": [
            {
                "ref": "e1",
                "target_id": "stable_node_A",
                "name": "Save",
                "role": "button",
                "scope": {"keys": [["data-record", "A"]], "text": "Record A"},
            }
        ],
    }
    args = {"action": "click", "ref": "e1", "observation_id": "old"}
    previous = service.approval_fingerprint("t", args, "task")
    assert service.approval_fingerprint("t", args, "task") == previous
    run.latest_observation["elements"][0]["ref"] = "e9"
    args.update(ref="e9")
    task = "task"
    if changed == "observation":
        run.latest_observation["observation_id"] = "new"
        args["observation_id"] = "new"
    elif changed == "node":
        run.latest_observation["elements"][0]["target_id"] = "stable_node_B"
    elif changed == "record":
        run.latest_observation["elements"][0]["scope"]["keys"][0][1] = "B"
    elif changed == "document":
        run.latest_observation["document_id"] = "other"
    elif changed == "generation":
        run.generation += 1
    elif changed == "task":
        task = "other_task"
    elif changed == "effect":
        args["action"] = "fill"
        args["text"] = "different effect"
    elif changed == "truncated":
        run.latest_observation["elements"][0]["name_truncated"] = True
    current = service.approval_fingerprint("t", args, task)
    # Fingerprints must freeze their facts; later page mutation cannot rewrite an old approval.
    assert (json.dumps(previous, sort_keys=True) == json.dumps(current, sort_keys=True)) == (
        changed == "ref_only"
    )


async def test_unknown_operation_blocks_new_mutation_and_requires_human_review(
    tmp_path, monkeypatch
):
    service = BrowserService(tmp_path)
    run = BrowserRun(
        "t", tmp_path, session=SimpleNamespace(_internal=SimpleNamespace(client=object()))
    )
    service.runs["t"] = run

    async def interrupted(run, action):
        run.last_dispatch_id = action._action_id
        raise RuntimeError("acknowledgement lost")

    monkeypatch.setattr(service, "_action", interrupted)
    monkeypatch.setattr("deepseek_tui.browser.service.observe", AsyncMock(return_value={}))
    with pytest.raises(BrowserActionError) as error:
        await service.action("t", BrowserAction(action="reload"))
    action_id = error.value.response["receipt"]["action_id"]
    assert service.operation("t", action_id)["receipt"]["execution"] == "unknown"
    blocked = await service.action("t", BrowserAction(action="reload"))
    assert blocked["receipt"]["execution"] == "not_executed"
    assert blocked["receipt"]["retry_kind"] == "inspect_unknown"
    with pytest.raises(ValueError, match="Only human"):
        await service.action(
            "t",
            BrowserAction(
                action="resolve_operation",
                operation_id=action_id,
                outcome="executed",
                reason="model guess",
            ),
        )
    result = await service.action(
        "t",
        BrowserAction(
            action="resolve_operation",
            operation_id=action_id,
            outcome="executed",
            reason="I checked the exact affected record",
        ),
        actor="user",
    )
    assert result["receipt"]["reconciliation"]["source"] == "human_review" and not run.unresolved
    # Reconciliation preserves the original unknown execution fact and records its human assessment.
    assert result["receipt"]["execution"] == "unknown"


async def test_key_release_is_sent_even_when_down_acknowledgement_is_lost():
    from deepseek_tui.browser.input import press_key

    client = SimpleNamespace(send=AsyncMock(side_effect=[ConnectionError("lost"), {}]))
    run = SimpleNamespace(generation=1)
    with pytest.raises(ConnectionError):
        await press_key(run, "Enter", client=client)
    assert [call.args[1]["type"] for call in client.send.call_args_list] == ["keyDown", "keyUp"]


async def test_browser_image_caption_describes_actual_wire_resize_and_crop(monkeypatch, tmp_path):
    from deepseek_tui.client.media import prepare_media_request
    from deepseek_tui.config.models import Config, ProviderConfig
    from deepseek_tui.media import import_image
    from deepseek_tui.protocol.messages import Message, MessageRequest

    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path))
    data = io.BytesIO()
    Image.new("RGB", (2000, 1000), "white").save(data, "PNG")
    block = import_image(data.getvalue()).model_copy(
        update={
            "crop": (100, 100, 1000, 500),
            "source": {
                "kind": "browser",
                "action_id": "capture",
                "observation_id": "obs",
                "pixel_to_css": {"scale_x": 0.6, "scale_y": 0.6, "offset_x": 0, "offset_y": 0},
            },
        }
    )
    config = Config(providers={"deepseek": ProviderConfig(image_max_side=512)})
    request = MessageRequest(
        model="unknown-capability", messages=[Message.user("look", images=[block])]
    )
    projected = await prepare_media_request(request, config, {})
    caption = projected.messages[0].content[-1].text
    source = json.loads(caption.split("\n", 1)[1])[0]
    assert source["wire_width"] == 512 and source["wire_height"] == 256
    assert source["wire_to_css"] == {
        "scale_x": 600 / 512,
        "scale_y": 300 / 256,
        "offset_x": 60,
        "offset_y": 60,
    }
    assert len(request.messages[0].content) == 2 and block.source["observation_id"] == "obs"


async def test_tab_cache_avoids_repeated_enumeration_and_force_refreshes(tmp_path):
    service = BrowserService(tmp_path)
    session = SimpleNamespace(
        list_tabs=AsyncMock(
            return_value=SimpleNamespace(
                success=True, metadata={"tabs": [{"tab_id": "main", "active": True}]}
            )
        )
    )
    run = BrowserRun("t", tmp_path, session=session)
    await service._refresh_tabs(run)
    await service._refresh_tabs(run)
    session.list_tabs.assert_awaited_once()
    await service._refresh_tabs(run, force=True)
    assert session.list_tabs.await_count == 2


async def test_repeated_rejections_use_business_progress_not_observation_ids(tmp_path, monkeypatch):
    service = BrowserService(tmp_path)
    run = BrowserRun("t", tmp_path)
    monkeypatch.setattr("deepseek_tui.browser.service.observe", AsyncMock(return_value={}))
    for i in range(3):
        run.latest_observation = {
            "observation_id": str(i),
            "document_id": "doc",
            "elements": [
                {"ref": str(i), "target_id": "same", "name": "Save", "scope": {"text": "Record A"}}
            ],
        }
        result = await service._reject_action(
            run, BrowserAction(action="click", ref=str(i)), "target_disabled"
        )
    assert result["receipt"]["no_progress_count"] == 3
    assert result["receipt"]["retry_kind"] == "change_route_or_assistance"


async def test_mixed_failures_escalate_across_successful_observations(tmp_path, monkeypatch):
    service = BrowserService(tmp_path)
    run = BrowserRun("t", tmp_path)
    monkeypatch.setattr("deepseek_tui.browser.service.observe", AsyncMock(return_value={}))
    for i, reason in enumerate(
        ["focus_not_active", "target_obscured", "screenshot_pixels_changed"]
    ):
        result = await service._reject_action(
            run, BrowserAction(action="click", selector="#target"), reason
        )
        service._remember_response(
            run,
            {
                "success": True,
                "content": "observed",
                "receipt": {"action_id": f"read-{i}", "action": "observe", "execution": "executed"},
            },
            persist=False,
        )
    assert result["receipt"]["consecutive_action_failures"] == 3
    assert result["receipt"]["retry_kind"] == "change_route_or_assistance"
    service._remember_response(
        run,
        {
            "success": True,
            "content": "done",
            "receipt": {"action_id": "good", "action": "click", "execution": "executed"},
        },
        persist=False,
    )
    assert run.consecutive_action_failures == 0


def test_dispatched_scroll_without_movement_counts_toward_recovery(tmp_path):
    service = BrowserService(tmp_path)
    run = BrowserRun("t", tmp_path)
    for i in range(3):
        result = service._remember_response(run, {
            "success": True, "content": "No observed movement",
            "receipt": {"action_id": str(i), "action": "scroll",
                        "execution": "executed", "effect": "not_confirmed"},
        }, persist=False)
    assert result["receipt"]["consecutive_action_failures"] == 3
    assert result["receipt"]["retry_kind"] == "change_route_or_assistance"
