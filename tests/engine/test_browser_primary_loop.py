"""Browser tasks use the ordinary model/tool loop, without a second assessor."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.client.base import LLMClient
from deepseek_tui.config.models import Config, FeatureConfig
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.engine.orchestrator import Engine
from deepseek_tui.protocol.messages import Message
from deepseek_tui.protocol.responses import (
    StreamDone,
    StreamTextDelta,
    StreamToolCallComplete,
    ToolCall,
)


class ScriptedClient(LLMClient):
    def __init__(self, replies):
        super().__init__()
        self.replies = iter(replies)
        self.requests = []

    async def stream_chat_completion(self, request):
        self.requests.append(request)
        reply = next(self.replies)
        if isinstance(reply, ToolCall):
            yield StreamToolCallComplete(tool_call=reply)
        else:
            yield StreamTextDelta(text=reply)
        yield StreamDone()


@pytest.mark.parametrize("final", ["Here is the result.", "Which area should I search?"])
async def test_primary_answer_is_not_reinterpreted(tmp_path, final):
    client = ScriptedClient([final])
    engine = await Engine.create(
        handle=EngineHandle(),
        client=client,
        working_directory=tmp_path,
        config=Config(
            features=FeatureConfig(tasks=False, subagents=False, mcp=False, automations=False)
        ),
        start_mcp=False,
    )
    engine.tool_context.metadata.update(browser_service=object(), runtime_thread_id="t")
    try:
        result = await engine._run_conversation(
            [Message.user("Use the browser")], "test", "sys", None
        )
        assert len(client.requests) == 1
        assert result.assistant_message.text_content() == final
    finally:
        await engine.shutdown_session()


async def test_tool_failure_returns_to_primary_model_for_recovery(tmp_path):
    client = ScriptedClient(
        [
            ToolCall(
                id="open",
                name="browser_use",
                arguments={"action": "open", "url": "https://example.test"},
            ),
            ToolCall(id="read", name="browser_use", arguments={"action": "observe"}),
            "The report total is 42.",
        ]
    )
    browser = SimpleNamespace(
        action=AsyncMock(
            side_effect=[
                {
                    "success": False,
                    "content": "Page load timed out; observe the current page before retrying.",
                },
                {
                    "success": True,
                    "content": "Report total: 42",
                    "observation": {"observation_id": "o", "text": "Report total: 42"},
                },
            ]
        )
    )
    engine = await Engine.create(
        handle=EngineHandle(),
        client=client,
        working_directory=tmp_path,
        config=Config(
            features=FeatureConfig(tasks=False, subagents=False, mcp=False, automations=False)
        ),
        start_mcp=False,
    )
    engine.tool_context.metadata.update(browser_service=browser, runtime_thread_id="t")
    engine._handle_approval_flow = AsyncMock(return_value=False)
    try:
        result = await engine._run_conversation(
            [Message.user("Read the report")], "test", "sys", None
        )
        assert len(client.requests) == 3
        assert [c.args[1].action for c in browser.action.call_args_list] == ["open", "observe"]
        assert result.assistant_message.text_content() == "The report total is 42."
        assert any(
            "Report total: 42" in b.content
            for m in client.requests[-1].messages
            for b in m.content
            if b.type == "tool_result"
        )
        assert not any("supplied schema" in str(r.system_prompt) for r in client.requests)
    finally:
        await engine.shutdown_session()


async def test_large_observation_survives_actual_engine_tool_ingress(tmp_path, monkeypatch):
    import json

    from deepseek_tui.config.models import ProviderConfig

    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path))
    observation = {
        "observation_id": "obs-current",
        "tab_id": "tab",
        "document_id": "doc",
        "control_generation": 4,
        "text": "Long page. " * 5000,
        "elements": [
            {"ref": f"e{i}", "role": "button", "name": "Action " * 40} for i in range(250)
        ],
    }
    browser = SimpleNamespace(
        action=AsyncMock(
            return_value={
                "success": True,
                "content": "Observation collected",
                "observation": observation,
                "receipt": {"execution": "executed", "effect": "unchecked"},
            }
        )
    )
    client = ScriptedClient(
        [
            ToolCall(id="read", name="browser_use", arguments={"action": "observe"}),
            "Read.",
        ]
    )
    engine = await Engine.create(
        handle=EngineHandle(),
        client=client,
        working_directory=tmp_path,
        config=Config(
            providers={"deepseek": ProviderConfig(context_windows={"test": 128_000})},
            features=FeatureConfig(
                tasks=False,
                subagents=False,
                mcp=False,
                automations=False,
            ),
        ),
        start_mcp=False,
    )
    engine.tool_context.metadata.update(browser_service=browser, runtime_thread_id="t")
    engine._ingress_pressure_ratio = lambda model: 0.6
    try:
        await engine._run_conversation([Message.user("Read this page")], "test", "sys", None)
        content = next(
            b.content
            for m in client.requests[-1].messages
            for b in m.content
            if b.type == "tool_result" and b.tool_use_id == "read"
        )
        result = json.loads(content)
        assert len(content) <= 6000
        assert result["receipt"]["execution"] == "executed"
        assert result["observation"]["observation_id"] == "obs-current"
        assert result["observation"]["elements"][0]["ref"] == "e0"
        assert result["observation"]["next_element_offset"] > 0
    finally:
        await engine.shutdown_session()
