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
            ToolCall(id="finish", name="finish_task", arguments={
                "status": "completed", "answer": "The report total is 42.",
                "evidence": ["tool:read"], "remaining": [],
            }),
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
            ToolCall(id="finish", name="finish_task", arguments={
                "status": "completed", "answer": "Read.",
                "evidence": ["tool:read"], "remaining": [],
            }),
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
        assert result["receipt"]["evidence_ref"] == "tool:read"
        assert result["observation"]["observation_id"] == "obs-current"
        assert result["observation"]["elements"][0]["ref"] == "e0"
        assert result["observation"]["next_element_offset"] > 0
    finally:
        await engine.shutdown_session()


def finish(answer="The total is 42."):
    return ToolCall(id="finish", name="finish_task", arguments={
        "status": "completed", "answer": answer, "evidence": ["tool:read"], "remaining": [],
    })


async def delivery_engine(tmp_path, replies):
    client = ScriptedClient(replies)
    engine = await Engine.create(handle=EngineHandle(), client=client, working_directory=tmp_path,
        config=Config(features=FeatureConfig(tasks=False, subagents=False, mcp=False, automations=False)),
        start_mcp=False)
    engine.tool_context.metadata.update(runtime_thread_id="t", browser_service=SimpleNamespace(
        action=AsyncMock(return_value={"success": True, "content": "Total 42",
                                     "observation": {"observation_id": "o", "text": "Total 42"}})))
    engine._handle_approval_flow = AsyncMock(return_value=False)
    engine.reply_locale = "en"
    return engine, client


@pytest.mark.parametrize("early_stop", [False, True])
@pytest.mark.parametrize("locale", ["en", "zh"])
async def test_delivery_returns_exact_answer_without_finalization_notice(tmp_path, early_stop, locale):
    from deepseek_tui.engine.events import StatusEvent, TextDeltaEvent
    engine, client = await delivery_engine(tmp_path, [
        ToolCall(id="read", name="browser_use", arguments={"action": "observe"}),
        *(["I opened the page."] if early_stop else []), finish(),
    ])
    engine.reply_locale = locale
    try:
        result = await engine._run_conversation([Message.user("Read total")], "test", "sys", None)
        assert len(client.requests) == 2 + early_stop  # no model call to rewrite the accepted delivery
        assert result.assistant_message.text_content() == "The total is 42."
        assert result.task_outcome["status"] == "completed"
        events = engine.handle.drain_events()
        assert any(isinstance(e, TextDeltaEvent) and e.text == "The total is 42."
                   for e in events)
        assert not any(isinstance(e, StatusEvent) and (
            "Finalizing existing results" in e.message or "正在整理已有结果" in e.message
        ) for e in events)
    finally:
        await engine.shutdown_session()


async def test_announced_step_without_tool_call_can_still_be_taken(tmp_path):
    engine, client = await delivery_engine(tmp_path, [
        ToolCall(id="look", name="browser_use", arguments={"action": "observe"}),
        "I'll open the report next.",
        ToolCall(id="read", name="browser_use", arguments={"action": "observe"}),
        finish(),
    ])
    try:
        result = await engine._run_conversation([Message.user("Read total")], "test", "sys", None)
        assert len(client.requests) == 4
        assert "browser_use" in {(t.get("function") or t)["name"] for t in client.requests[2].tools}
        assert result.task_outcome["status"] == "completed"
    finally:
        await engine.shutdown_session()


async def test_repeated_unstructured_stop_is_partial_not_infinite_loop(tmp_path):
    engine, client = await delivery_engine(tmp_path, [
        ToolCall(id="read", name="browser_use", arguments={"action": "observe"}),
        "Opened.", "Opened.", "Opened.",
    ])
    try:
        result = await engine._run_conversation([Message.user("Read total")], "test", "sys", None)
        # One round to continue, one to finalize, then a bounded partial.
        assert len(client.requests) == 4
        assert result.task_outcome["status"] == "partial"
        assert "not verified" in result.assistant_message.text_content()
    finally:
        await engine.shutdown_session()


async def test_focus_blocks_hidden_tool_then_enables_only_requested_tool(tmp_path):
    (tmp_path / "report.txt").write_text("42")
    engine, client = await delivery_engine(tmp_path, [
        ToolCall(id="read", name="browser_use", arguments={"action": "observe"}),
        ToolCall(id="hidden", name="write_file", arguments={"path": "report.txt", "content": "43"}),
        ToolCall(id="extend", name="request_task_tools", arguments={
            "names": ["write_file"], "reason": "Save analyzed report"}),
        ToolCall(id="file", name="write_file", arguments={"path": "report.txt", "content": "43"}),
        finish(),
    ])
    try:
        result = await engine._run_conversation([Message.user("Read report")], "test", "sys", None)
        names = lambda req: {(t.get("function") or t)["name"] for t in req.tools}
        # Only basic tools are exposed until a capability is explicitly requested.
        assert "write_file" not in names(client.requests[1])
        assert "write_file" in names(client.requests[3])
        assert "read_file" in names(client.requests[1])
        tool_results = {b.tool_use_id: b for m in client.requests[-1].messages
                        for b in m.content if b.type == "tool_result"}
        assert tool_results["hidden"].is_error
        assert not tool_results["file"].is_error
        assert result.task_outcome["status"] == "completed"
        # Focus and evidence belong to one task, not the next conversation turn.
        client.replies = iter(["Hello"])
        result = await engine._run_conversation([Message.user("Hello")], "test", "sys", None)
        assert result.task_outcome is None and "read_file" in names(client.requests[-1])
        assert not {"finish_task", "request_task_tools"} & names(client.requests[-1])
    finally:
        await engine.shutdown_session()


async def test_delivery_on_last_tool_round_still_reaches_user(tmp_path):
    engine, client = await delivery_engine(tmp_path, [
        ToolCall(id="read", name="browser_use", arguments={"action": "observe"}), finish(),
    ])
    engine.max_tool_round_trips = 1
    try:
        result = await engine._run_conversation([Message.user("Read")], "test", "sys", None)
        assert len(client.requests) == 2
        assert result.task_outcome["status"] == "completed"
        assert result.assistant_message.text_content() == "The total is 42."
    finally:
        await engine.shutdown_session()


@pytest.mark.parametrize("control,args", [
    ("request_task_tools", {"names": ["read_file"], "reason": "Read report"}),
    ("finish_task", {"status": "blocked", "answer": "Blocked", "evidence": [], "remaining": ["Login"]}),
    ("request_user_input", {"questions": [{"id": "order", "header": "Order", "question": "Which?"}]}),
])
async def test_control_calls_cannot_race_a_browser_action(tmp_path, control, args):
    engine, _ = await delivery_engine(tmp_path, [])
    try:
        results = await engine._execute_tool_calls([
            ToolCall(id="control", name=control, arguments=args),
            ToolCall(id="open", name="browser_use", arguments={"action": "open", "url": "https://example.test"}),
        ])
        assert len(results) == 2
        assert all(r.content[0].is_error for r in results)
        engine.tool_context.metadata["browser_service"].action.assert_not_awaited()
        assert not engine.handle.pending_user_inputs
    finally:
        await engine.shutdown_session()


async def test_expanding_tools_does_not_bypass_approval(tmp_path):
    engine, client = await delivery_engine(tmp_path, [
        ToolCall(id="read", name="browser_use", arguments={"action": "observe"}),
        ToolCall(id="expand", name="request_task_tools", arguments={"names": ["write_file"], "reason": "Save report"}),
        ToolCall(id="denied", name="write_file", arguments={"path": "report.txt", "content": "42"}),
        ToolCall(id="finish", name="finish_task", arguments={"status": "partial", "answer": "Total 42; file not saved.",
            "evidence": ["tool:read"], "remaining": ["File write was denied"]}),
    ])
    engine._handle_approval_flow = AsyncMock(return_value=True)
    try:
        result = await engine._run_conversation([Message.user("Save the report")], "test", "sys", None)
        assert result.task_outcome["status"] == "partial"
        assert not (tmp_path / "report.txt").exists()
        assert any(c.args[0].name == "write_file" for c in engine._handle_approval_flow.call_args_list)
    finally:
        await engine.shutdown_session()


async def test_provider_failure_after_browser_returns_blocked_delivery(tmp_path):
    from deepseek_tui.protocol.responses import StreamError

    class FailingClient(ScriptedClient):
        async def stream_chat_completion(self, request):
            if self.requests:
                self.requests.append(request)
                yield StreamError(message="HTTP 413: Payload too large", retryable=False)
            else:
                async for event in super().stream_chat_completion(request):
                    yield event

    client = FailingClient(
        [
            ToolCall(
                id="open",
                name="browser_use",
                arguments={"action": "open", "url": "https://example.test"},
            )
        ]
    )
    browser = SimpleNamespace(
        action=AsyncMock(return_value={"success": True, "content": "Page opened"})
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
            [Message.user("Find nearby places")], "test", "sys", None
        )
        assert len(client.requests) == 2
        assert result.task_outcome["status"] == "blocked"
        assert "413" in result.task_outcome["remaining"][0]
        assert result.error_message and result.assistant_message.text_content()
        assert "tool:open" in result.task_outcome["evidence"]
    finally:
        await engine.shutdown_session()


@pytest.mark.parametrize("recover", [True, False])
async def test_rejected_delivery_has_one_correction_without_repeating_unverified_answer(tmp_path, recover):
    wrong = ToolCall(id="bad-finish", name="finish_task", arguments={
        "status": "completed", "answer": "The report says 42.",
        "evidence": ["tool:browser-action-id"], "remaining": [],
    })
    engine, client = await delivery_engine(tmp_path, [
        ToolCall(id="read", name="browser_use", arguments={"action": "observe"}),
        wrong, finish() if recover else wrong,
    ])
    try:
        result = await engine._run_conversation([Message.user("Read total")], "test", "sys", None)
        assert len(client.requests) == 3
        assert {(t.get("function") or t)["name"] for t in client.requests[-1].tools} == {"finish_task"}
        errors = [b.content for m in client.requests[-1].messages for b in m.content
                  if b.type == "tool_result" and b.is_error]
        assert any("tool:read" in e and "action_id" in e for e in errors)
        assert result.task_outcome["status"] == ("completed" if recover else "partial")
        if recover:
            assert "The total is 42." in result.assistant_message.text_content()
        else:
            assert "not verified" in result.assistant_message.text_content()
            assert "The report says 42." not in result.assistant_message.text_content()
    finally:
        await engine.shutdown_session()


async def test_progress_narration_is_never_reused_as_answer(tmp_path):
    engine, client = await delivery_engine(tmp_path, [
        ToolCall(id="read", name="browser_use", arguments={"action": "observe"}),
        "Retry with the screenshot ID.", "Trying again.", "Trying again.",
    ])
    try:
        result = await engine._run_conversation([Message.user("Read total")], "test", "sys", None)
        assert len(client.requests) == 4
        assert result.task_outcome["status"] == "partial"
        assert "Retry" not in result.assistant_message.text_content()
        assert "Trying" not in result.assistant_message.text_content()
    finally:
        await engine.shutdown_session()


async def test_malformed_finish_also_has_bounded_correction(tmp_path):
    engine, client = await delivery_engine(tmp_path, [
        ToolCall(id="read", name="browser_use", arguments={"action": "observe"}),
        ToolCall(id="bad", name="finish_task", arguments={"answer": "Incomplete schema"}),
        finish(),
    ])
    try:
        result = await engine._run_conversation([Message.user("Read total")], "test", "sys", None)
        assert len(client.requests) == 3
        assert {(t.get("function") or t)["name"] for t in client.requests[-1].tools} == {"finish_task"}
        assert result.task_outcome["status"] == "completed"
    finally:
        await engine.shutdown_session()


async def test_stalled_correction_times_out_without_unverified_answer(tmp_path, monkeypatch):
    import asyncio

    monkeypatch.setattr("deepseek_tui.tools.task_delivery.FINALIZATION_TIMEOUT_SECONDS", 0.01)
    engine, client = await delivery_engine(tmp_path, [
        ToolCall(id="read", name="browser_use", arguments={"action": "observe"}),
        ToolCall(id="bad", name="finish_task", arguments={
            "status": "completed", "answer": "The report says 42.",
            "evidence": ["tool:wrong"], "remaining": [],
        }),
    ])
    stream = client.stream_chat_completion

    async def stalled(request):
        if len(client.requests) == 2:
            client.requests.append(request)
            await asyncio.Event().wait()
        async for event in stream(request):
            yield event

    monkeypatch.setattr(client, "stream_chat_completion", stalled)
    try:
        result = await engine._run_conversation([Message.user("Read total")], "test", "sys", None)
        assert len(client.requests) == 3
        assert result.task_outcome["status"] == "partial"
        assert "The report says 42." not in result.assistant_message.text_content()
        assert "timed out" in result.task_outcome["remaining"][0]
    finally:
        await engine.shutdown_session()


@pytest.mark.parametrize("locale,text", [("zh", "正在重试"), ("en", "retrying")])
async def test_connection_retries_are_visible_once_per_request(tmp_path, locale, text):
    from deepseek_tui.engine.events import StatusEvent
    from deepseek_tui.protocol.responses import StreamRetry

    class RetryingClient(ScriptedClient):
        async def stream_chat_completion(self, request):
            self.requests.append(request)
            yield StreamRetry(attempt=1)
            yield StreamRetry(attempt=2)
            yield StreamTextDelta(text="Done.")
            yield StreamDone()

    client = RetryingClient([])
    engine = await Engine.create(
        handle=EngineHandle(), client=client, working_directory=tmp_path,
        config=Config(features=FeatureConfig(
            tasks=False, subagents=False, mcp=False, automations=False)),
        start_mcp=False,
    )
    engine.reply_locale = locale
    try:
        result = await engine._run_conversation([Message.user("Hi")], "test", "sys", None)
        assert result.assistant_message.text_content() == "Done."
        notes = [e for e in engine.handle.drain_events()
                 if isinstance(e, StatusEvent) and text in e.message]
        assert len(notes) == 1
    finally:
        await engine.shutdown_session()
