"""Browser observations must remain actionable after model context budgeting."""

import json

import pytest

from deepseek_tui.engine.context import compact_tool_result_for_context
from deepseek_tui.tools.registry import ToolResult


@pytest.mark.parametrize("budget", [6000, 12000, 36000])
@pytest.mark.parametrize("branch", ["status", "scope", "unknown"])
def test_every_response_branch_obeys_budget(budget, branch):
    from deepseek_tui.browser.context import project_result

    data = {"success": True, "content": {"active": True, "generation": 3,
        "log": [{"receipt": "x" * 1000} for _ in range(80)]}}
    if branch == "scope":
        data = {"success": True, "observation": {"observation_id": "obs-long-scope",
            "scope_shadow_path": ["#" + "a" * 999 for _ in range(16)],
            "text": "文字😀" * 20000, "elements": [{"ref": "e0", "name": "Go"}]}}
    elif branch == "unknown":
        data = {"success": False, "content": "failure " * 10000,
            "receipt": {"action_id": "pending", "execution": "unknown", "effect": "unchecked"}}
    output = project_result(data, budget)
    parsed = json.loads(output)
    assert len(output) <= budget
    output.encode("utf-8")
    if branch == "scope":
        assert parsed["observation"]["observation_id"] == "obs-long-scope"
    if branch == "unknown":
        assert parsed["receipt"]["execution"] == "unknown"


@pytest.mark.parametrize("pressure", [None, 0.1, 0.3, 0.6])
def test_browser_context_preserves_identity_and_complete_targets(pressure):
    observation = {
        "observation_id": "obs-current",
        "tab_id": "tab",
        "document_id": "doc",
        "control_generation": 3,
        "url": "https://example.test",
        "title": "Results",
        "text": "Reading material. " * 2000,
        "elements": [
            {"ref": f"e{i}", "role": "button", "name": "Control " * 40} for i in range(100)
        ],
        "warnings": ["Unreadable frame"],
        "element_offset": 0,
        "text_offset": 0,
    }
    result = {
        "success": True,
        "content": "Observation collected",
        "observation": observation,
        "receipt": {"execution": "executed"},
    }
    output = ToolResult(True, json.dumps(result), metadata={"browser": result})
    projected = compact_tool_result_for_context(
        "gpt-4o", "browser_use", output, pressure_ratio=pressure
    )
    data = json.loads(projected)
    assert data["observation"]["observation_id"] == "obs-current"
    assert data["observation"]["control_generation"] == 3
    assert data["receipt"]["execution"] == "executed"
    assert data["observation"]["warnings"] == ["Unreadable frame"]
    assert data["observation"]["elements"][0]["ref"] == "e0"
    if len(data["observation"]["elements"]) < 100:
        assert data["observation"]["next_element_offset"] > 0
    assert len(projected) <= (36000 if pressure == 0.1 else 12000)


def test_browser_projection_uses_metadata_after_spillover():
    result = {
        "success": True,
        "observation": {
            "observation_id": "obs-current",
            "elements": [{"ref": "e0", "role": "button", "name": "Go"}],
            "text": "Page",
        },
    }
    output = ToolResult(True, "[Output truncated; read_file ...]", metadata={"browser": result})
    data = json.loads(compact_tool_result_for_context("gpt-4o", "browser_use", output))
    assert data["observation"]["elements"][0]["ref"] == "e0"


def test_shadow_scope_survives_context_pressure_for_continuation():
    from deepseek_tui.browser.context import project_result

    result = {
        "success": True,
        "observation": {
            "observation_id": "obs-shadow",
            "scope_shadow_path": ["#host", "#nested"],
            "scope_selector": "#options",
            "text": "reading " * 3000,
            "elements": [{"ref": f"e{i}", "name": "Choice"} for i in range(250)],
        },
    }
    output = project_result(result, 6000)
    observation = json.loads(output)["observation"]
    assert len(output) <= 6000 and observation["scope_shadow_path"] == ["#host", "#nested"]
    assert observation["scope_selector"] == "#options" and observation["next_element_offset"] > 0


def test_large_options_and_frame_catalog_do_not_starve_targets():
    result = {
        "success": True,
        "content": "Observed",
        "page": {"url": "u" * 5000},
        "observation": {
            "observation_id": "obs-current",
            "tab_id": "tab",
            "document_id": "doc",
            "url": "u" * 5000,
            "title": "t" * 5000,
            "text": '"\\' * 30000,
            "frames": [{"frame_id": f"frame{i}", "url": "f" * 4000} for i in range(20)],
            "elements": [
                {
                    "ref": "e0",
                    "role": "select",
                    "name": "N" * 300,
                    "options": [{"value": "v" * 500, "text": "t" * 500} for _ in range(100)],
                }
            ],
        },
    }
    projected = compact_tool_result_for_context(
        "gpt-4o",
        "browser_use",
        ToolResult(True, json.dumps(result), metadata={"browser": result}),
        pressure_ratio=0.6,
    )
    assert len(projected) <= 6000
    data = json.loads(projected)
    assert data["observation"]["elements"][0]["ref"] == "e0"
    assert data["observation"]["next_frame_offset"] == 2


@pytest.mark.parametrize("budget", [1_000_000, 6000])
def test_scroll_positions_survive_context_pressure(budget):
    from deepseek_tui.browser.context import project_result

    viewport = {"width": 1200, "height": 760, "scroll_x": 0, "scroll_y": 1600,
                "scroll_width": 1200, "scroll_height": 4000}
    containers = [
        {"ref": f"c{i}", "role": "div", "tag": "div", "name": "N" * 80,
         "box": {"x": 0, "y": 0, "width": 300, "height": 200}, "viewport": dict(viewport)}
        for i in range(10)
    ]
    result = {"success": True, "observation": {
        "observation_id": "obs", "text": "t" * (20000 if budget == 6000 else 10),
        "elements": [{"ref": "e0", "role": "button", "name": "Go"}], "viewport": viewport,
        "scroll_containers": containers, "total_scroll_containers": 10}}
    output = project_result(result, budget)
    observation = json.loads(output)["observation"]
    assert len(output) <= budget
    assert observation["viewport"] == viewport and observation["total_scroll_containers"] == 10
    assert [c["ref"] for c in observation["scroll_containers"]] == (
        ["c0", "c1", "c2"] if budget == 6000 else [f"c{i}" for i in range(10)])


@pytest.mark.parametrize("budget", [1_000_000, 3000])
def test_projection_lists_shared_scope_once_and_drops_backend_fields(budget):
    from deepseek_tui.browser.context import project_result

    def row(i):
        return {"tag": "tr", "id": "", "keys": [["data-row-key", f"r{i}"]], "text": f"Item {i}"}

    elements = [
        {"ref": f"e{2 * i + j}", "target_id": f"obs_x:n{2 * i + j}", "role": "button",
         "tag": "button", "name": name, "disabled": False, "editable": False, "readonly": False,
         "box": {"x": 1.5, "y": 2.5, "width": 3, "height": 4}, "scope": row(i)}
        for i in range(40) for j, name in enumerate(("Edit", "Delete"))
    ]
    result = {"success": True, "observation": {"observation_id": "obs", "text": "t",
                                               "elements": elements}}
    observation = json.loads(project_result(result, budget))["observation"]
    first, second = observation["elements"][:2]
    assert first == {"ref": "e0", "role": "button", "name": "Edit", "scope": "s0"}
    assert second["scope"] == "s0" and observation["scopes"]["s0"] == row(0)
    assert {e["scope"] for e in observation["elements"]} == set(observation["scopes"])
    if budget == 3000:
        assert observation["next_element_offset"] == len(observation["elements"]) < 80


def test_runtime_without_browser_does_not_advertise_browser_tool(tmp_path):
    from deepseek_tui.tools.browser import BrowserUseTool
    from deepseek_tui.tools.registry import ToolContext, ToolRegistry

    context = ToolContext(working_directory=tmp_path, metadata={})
    registry = ToolRegistry(context)
    registry.register(BrowserUseTool())
    assert registry.to_api_tools() == []
    context.metadata.update(browser_service=object(), runtime_thread_id="thread")
    assert registry.to_api_tools()[0]["function"]["name"] == "browser_use"


def test_compaction_preserves_exact_option_values_and_continuation():
    from deepseek_tui.browser.context import project_result

    values = [f"{i}-" + "v" * 500 for i in range(100)]
    result = {
        "success": True,
        "observation": {
            "observation_id": "obs",
            "elements": [
                {
                    "ref": "e0",
                    "role": "select",
                    "option_offset": 10,
                    "options": [{"value": v, "text": "Choice"} for v in values],
                }
            ],
            "text": "t" * 30000,
        },
    }
    data = json.loads(project_result(result, 6000))
    select = data["observation"]["elements"][0]
    assert select["options"][0]["value"] == values[0]
    assert select["next_option_offset"] == 10 + len(select["options"])


async def test_vision_helper_receives_current_operation_without_input_values(tmp_path, monkeypatch):
    import io
    from unittest.mock import patch

    from PIL import Image

    from deepseek_tui.client.base import LLMClient
    from deepseek_tui.client.media import prepare_media_request
    from deepseek_tui.config.models import Config, ProviderConfig, VisionConfig
    from deepseek_tui.media import import_image
    from deepseek_tui.protocol.messages import (
        Message,
        MessageRequest,
        Role,
        ToolResultBlock,
        ToolUseBlock,
    )
    from deepseek_tui.protocol.responses import StreamDone, StreamTextDelta

    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path))
    seen = []

    class Vision(LLMClient):
        async def stream_chat_completion(self, request):
            seen.append(request)
            yield StreamTextDelta(text="Observed field")
            yield StreamDone()

    data = io.BytesIO()
    Image.new("RGB", (2, 2), "red").save(data, format="PNG")
    image = import_image(data.getvalue())
    cfg = Config(
        vision=VisionConfig(model="visual::fixture"),
        providers={"visual": ProviderConfig(api_key="fake", image_input=True)},
    )
    cache = {}
    with patch("deepseek_tui.client.factory.build_llm_client", return_value=Vision()):
        for ref in ("e4", "e5"):
            request = MessageRequest(
                model="deepseek-chat",
                messages=[
                    Message.user("Read the report"),
                    Message(
                        role=Role.ASSISTANT,
                        content=[
                            ToolUseBlock(
                                id="fill",
                                name="browser_use",
                                input={
                                    "action": "fill",
                                    "ref": ref,
                                    "observation_id": "obs-current",
                                    "text": "PRIVATE_INPUT",
                                },
                            )
                        ],
                    ),
                    Message(
                        role=Role.TOOL,
                        content=[
                            ToolResultBlock(tool_use_id="fill", content="Completed", images=[image])
                        ],
                    ),
                ],
            )
            await prepare_media_request(request, cfg, cache)
    assert len(seen) == 2
    prompt = seen[0].messages[0].text_content()
    assert "obs-current" in prompt and '"ref": "e4"' in prompt
    assert "PRIVATE_INPUT" not in prompt
