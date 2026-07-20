"""Regression tests for P0 audit fixes (F3/F4/H2/H3)."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from deepseek_tui.engine.dispatch import (
    TASK_WALL_CLOCK_SECONDS,
    _collect_turn_events,
)
from deepseek_tui.engine.events import TextDeltaEvent, TurnCompleteEvent
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.engine.orchestrator.tooling import ToolExecutionMixin
from deepseek_tui.mcp.client import McpClient
from deepseek_tui.mcp.config import McpServerConfig
from deepseek_tui.mcp.transport import McpTransportError
from deepseek_tui.protocol.messages import Message
from deepseek_tui.tools.file import EditFileTool
from deepseek_tui.tools.registry import (
    ApprovalRequirement,
    ToolCapability,
    ToolContext,
    ToolError,
    ToolRegistry,
    ToolResult,
    ToolSpec,
)


@pytest.mark.asyncio
async def test_collect_turn_events_drains_concurrently_with_emit() -> None:
    """Producer must not block forever on a full queue while collector runs."""
    handle = EngineHandle()
    cancel = asyncio.Event()

    async def _flood() -> None:
        # More than enough to fill maxsize=4096 if nobody is consuming.
        for i in range(5000):
            await handle.emit(TextDeltaEvent(text=f"x{i}"))
        await handle.emit(
            TurnCompleteEvent(assistant_message=Message.assistant("done"))
        )

    flood = asyncio.create_task(_flood())
    text, err = await asyncio.wait_for(
        _collect_turn_events(handle, cancel), timeout=5.0
    )
    await asyncio.wait_for(flood, timeout=5.0)
    assert err is None
    assert text == "done"


@pytest.mark.asyncio
async def test_collect_turn_events_bridges_cancel_to_handle() -> None:
    handle = EngineHandle()
    cancel = asyncio.Event()

    async def _produce() -> None:
        await asyncio.sleep(0.05)
        cancel.set()
        # Collector only checks cancel when an event arrives.
        await handle.emit(TextDeltaEvent(text="ping"))

    producer = asyncio.create_task(_produce())
    collect = asyncio.create_task(_collect_turn_events(handle, cancel))
    text, err = await asyncio.wait_for(collect, timeout=2.0)
    await producer
    assert handle.cancel_event.is_set()
    assert err is None
    assert text == ""


@pytest.mark.asyncio
async def test_edit_file_rejects_empty_search(tmp_path) -> None:
    target = tmp_path / "sample.txt"
    target.write_text("hello", encoding="utf-8")
    with pytest.raises(ToolError, match="must not be empty"):
        await EditFileTool().execute(
            {"path": "sample.txt", "search": "", "replace": "x"},
            ToolContext(working_directory=tmp_path),
        )
    assert target.read_text(encoding="utf-8") == "hello"


@pytest.mark.asyncio
async def test_mcp_client_marks_dead_after_transport_error() -> None:
    class _BoomTransport:
        async def start(self) -> None:
            return None

        async def stop(self) -> None:
            return None

        async def send(self, message: dict[str, Any]) -> None:
            return None

        async def recv(self) -> dict[str, Any]:
            raise McpTransportError("peer gone")

    cfg = McpServerConfig(name="t", command=["true"])
    client = McpClient(cfg)
    client._transport = _BoomTransport()  # noqa: SLF001
    client._closed = False
    client._reader_task = asyncio.create_task(client._reader_loop())  # noqa: SLF001
    await asyncio.wait_for(client._reader_task, timeout=2.0)  # noqa: SLF001
    assert client.is_running is False
    assert client._closed is True  # noqa: SLF001


class _SuggestReadOnlyTool(ToolSpec):
    def name(self) -> str:
        return "suggest_readonly"

    def description(self) -> str:
        return "read-only but requires suggest approval"

    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.READ_ONLY, ToolCapability.NETWORK]

    def approval_requirement(self) -> ApprovalRequirement:
        return ApprovalRequirement.SUGGEST

    async def execute(
        self, input_data: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        return ToolResult(success=True, content="should not run")


@pytest.mark.asyncio
async def test_parallel_tool_rejects_approval_required_readonly() -> None:
    class _Harness(ToolExecutionMixin):
        def __init__(self) -> None:
            self.tool_registry = ToolRegistry()
            self.tool_registry.register(_SuggestReadOnlyTool())
            self.tool_context = ToolContext(working_directory=MagicMock())
            self.exec_policy = MagicMock()
            self.exec_policy.approval_policy = "on-request"

    harness = _Harness()
    result = await harness._execute_parallel_tools(
        {
            "tool_uses": [
                {"recipient_name": "suggest_readonly", "parameters": {}}
            ]
        }
    )
    assert result.success is False
    assert "requires approval" in result.content


@pytest.mark.asyncio
async def test_elevation_wait_rethrows_cancelled_error() -> None:
    """CancelledError must not be swallowed as elevation denial."""
    from deepseek_tui.protocol.responses import ToolCall
    from deepseek_tui.server.approval import ElevationBridge

    class _Harness(ToolExecutionMixin):
        def __init__(self) -> None:
            self.handle = EngineHandle()
            self.tool_context = ToolContext(working_directory=MagicMock())
            self.tool_context.metadata["runtime_thread_id"] = "t1"
            self.tool_context.metadata["elevation_bridge"] = ElevationBridge()
            self.tool_context.elevated_sandbox_policy = None
            self.tool_context.execution_sandbox_policy = None
            self.mode = "agent"

        async def _execute_single_tool(self, *args: Any, **kwargs: Any) -> ToolResult:
            raise AssertionError("retry must not run after cancel")

    harness = _Harness()
    bridge: ElevationBridge = harness.tool_context.metadata["elevation_bridge"]
    tool_call = ToolCall(id="c1", name="exec_shell", arguments={"command": "ls"})
    denied = ToolResult(
        success=False,
        content="Sandbox blocked",
        metadata={"sandbox_denied": True, "denial_message": "blocked"},
    )

    async def _cancel_pending() -> None:
        await asyncio.sleep(0)
        fut = bridge._pending.get("c1")  # noqa: SLF001
        assert fut is not None
        fut.cancel()

    cancel_task = asyncio.create_task(_cancel_pending())
    with pytest.raises(asyncio.CancelledError):
        await harness._maybe_elevate_and_retry_tool(
            tool_call, [], "deepseek-chat", denied
        )
    await cancel_task


@pytest.mark.asyncio
async def test_elevation_auto_approves_when_auto_approve_enabled() -> None:
    """auto_approve must skip the elevation bridge wait (no 600s stall)."""
    from deepseek_tui.engine.handle import AutoApprovalHandler
    from deepseek_tui.policy.sandbox import ExecutionSandboxPolicy
    from deepseek_tui.protocol.responses import ToolCall
    from deepseek_tui.server.approval import ElevationBridge

    class _Harness(ToolExecutionMixin):
        def __init__(self) -> None:
            self.handle = EngineHandle()
            self.approval_handler = AutoApprovalHandler()
            self.tool_context = ToolContext(working_directory=MagicMock())
            self.tool_context.metadata["runtime_thread_id"] = "t1"
            self.tool_context.metadata["elevation_bridge"] = ElevationBridge()
            self.tool_context.elevated_sandbox_policy = None
            self.tool_context.execution_sandbox_policy = (
                ExecutionSandboxPolicy.workspace_write(network_access=True)
            )
            self.mode = "agent"
            self.retry_calls = 0

        async def _execute_single_tool(self, *args: Any, **kwargs: Any) -> ToolResult:
            self.retry_calls += 1
            return ToolResult(success=True, content="ok")

    harness = _Harness()
    tool_call = ToolCall(id="c-auto", name="exec_shell", arguments={"command": "ls"})
    denied = ToolResult(
        success=False,
        content="Sandbox blocked",
        metadata={"sandbox_denied": True, "denial_message": "blocked"},
    )
    out = await harness._maybe_elevate_and_retry_tool(
        tool_call, [], "deepseek-chat", denied
    )
    assert out.success is True
    assert out.content == "ok"
    assert harness.retry_calls == 1
    bridge: ElevationBridge = harness.tool_context.metadata["elevation_bridge"]
    assert bridge.list_pending() == []


def test_task_wall_clock_constant_is_set() -> None:
    assert TASK_WALL_CLOCK_SECONDS == 7200
    assert TASK_WALL_CLOCK_SECONDS > 900


def test_approval_key_shell_distinguishes_paths() -> None:
    from deepseek_tui.policy.approval import build_approval_key

    a = build_approval_key("exec_shell", {"command": "rm a.txt"})
    b = build_approval_key("exec_shell", {"command": "rm b.txt"})
    assert a != b
    # Flags dropped: cosmetic option differences share a fingerprint.
    s1 = build_approval_key("exec_shell", {"command": "git status -s"})
    s2 = build_approval_key("exec_shell", {"command": "git status --porcelain"})
    assert s1 == s2


def test_approval_key_write_file_includes_path() -> None:
    from deepseek_tui.policy.approval import build_approval_key

    a = build_approval_key("write_file", {"path": "a.py", "content": "x"})
    b = build_approval_key("write_file", {"path": "b.py", "content": "x"})
    assert a != b
    assert "a.py" in a.value
    assert str(a).startswith("file:write_file:")


@pytest.mark.asyncio
async def test_run_tests_timeout_kills_process(tmp_path, monkeypatch) -> None:
    """Timed-out run_tests must kill the child (no zombie)."""
    from deepseek_tui.tools.validation import RunTestsTool

    killed = {"value": False}

    class _FakeProc:
        returncode = None

        def kill(self) -> None:
            killed["value"] = True
            self.returncode = -9

        async def wait(self) -> int:
            return -9

        async def communicate(self) -> tuple[bytes, bytes]:
            await asyncio.sleep(10)
            return b"", b""

    async def _fake_spawn(*_a: Any, **_k: Any) -> Any:
        return _FakeProc(), None

    monkeypatch.setattr(
        "deepseek_tui.tools.shell.spawn_sandboxed_shell", _fake_spawn
    )
    # Shrink wait_for timeout via wrapping communicate path: patch wait_for
    # only for the communicate call by using a short timeout in a local copy
    # is hard; instead patch wait_for to fail fast when timeout==300.
    real_wait_for = asyncio.wait_for

    async def _fast_timeout(awaitable: Any, *, timeout: float | None = None) -> Any:
        if timeout == 300:
            timeout = 0.01
        return await real_wait_for(awaitable, timeout=timeout)

    monkeypatch.setattr(asyncio, "wait_for", _fast_timeout)

    with pytest.raises(ToolError, match="timed out"):
        await RunTestsTool().execute(
            {"command": "sleep 999"},
            ToolContext(working_directory=tmp_path),
        )
    assert killed["value"] is True


@pytest.mark.asyncio
async def test_run_tests_routes_through_sandboxed_spawn(tmp_path, monkeypatch) -> None:
    """H7: run_tests must spawn via spawn_sandboxed_shell (workspace sandbox),
    not a bare create_subprocess_shell that escapes it."""
    from deepseek_tui.tools.validation import RunTestsTool

    called = {"value": False}

    class _FakeProc:
        returncode = 0

        async def communicate(self) -> tuple[bytes, bytes]:
            return b"ok", b""

    class _FakeExecEnv:
        sandbox_type = SimpleNamespace(value="none")

        def is_sandboxed(self) -> bool:
            return False

    async def _fake_spawn(command, cwd, context, timeout_ms):
        called["value"] = True
        assert command == "echo hi"
        return _FakeProc(), _FakeExecEnv()

    monkeypatch.setattr(
        "deepseek_tui.tools.shell.spawn_sandboxed_shell", _fake_spawn
    )

    result = await RunTestsTool().execute(
        {"command": "echo hi"},
        ToolContext(working_directory=tmp_path),
    )
    assert called["value"] is True
    payload = json.loads(result.content)
    assert payload["sandboxed"] is False
    assert payload["sandbox_type"] == "none"


def test_task_create_schema_omits_privilege_flags() -> None:
    from deepseek_tui.tools.task.tools import TaskCreateTool

    props = TaskCreateTool().input_schema()["properties"]
    assert "auto_approve" not in props
    assert "trust_mode" not in props
    assert "prompt" in props


def test_subagent_max_tokens_by_type() -> None:
    from deepseek_tui.tools.subagent import (
        SUBAGENT_MAX_TOKENS_READ,
        SUBAGENT_MAX_TOKENS_WRITE,
        SubAgentType,
        max_tokens_for_subagent_type,
    )

    assert SUBAGENT_MAX_TOKENS_READ == 8_192
    assert SUBAGENT_MAX_TOKENS_WRITE == 16_384
    for kind in (
        SubAgentType.EXPLORE,
        SubAgentType.PLAN,
        SubAgentType.REVIEW,
        SubAgentType.VERIFIER,
    ):
        assert max_tokens_for_subagent_type(kind) == SUBAGENT_MAX_TOKENS_READ
        assert kind.max_tokens() == SUBAGENT_MAX_TOKENS_READ
    for kind in (
        SubAgentType.GENERAL,
        SubAgentType.IMPLEMENTER,
        SubAgentType.CUSTOM,
    ):
        assert max_tokens_for_subagent_type(kind) == SUBAGENT_MAX_TOKENS_WRITE
        assert kind.max_tokens() == SUBAGENT_MAX_TOKENS_WRITE


@pytest.mark.asyncio
async def test_task_create_rejects_nested_task_context(tmp_path) -> None:
    from deepseek_tui.tools.task import TaskManager, TaskManagerConfig
    from deepseek_tui.tools.task.tools import TaskCreateTool

    async def _stub(task, cancel):  # noqa: ANN001
        from deepseek_tui.tools.task import TaskExecutionResult

        return TaskExecutionResult(summary="ok")

    manager = TaskManager(
        TaskManagerConfig(data_dir=tmp_path / "tasks", default_workspace=tmp_path),
        executor=_stub,
    )
    await manager.start()
    try:
        ctx = ToolContext(
            working_directory=tmp_path,
            task_manager=manager,
            active_task_id="task_parent",
        )
        with pytest.raises(ToolError, match="max_task_nest_depth"):
            await TaskCreateTool().execute({"prompt": "nested"}, ctx)

        # metadata-only nesting guard (sub-agent inside a task)
        ctx2 = ToolContext(
            working_directory=tmp_path,
            task_manager=manager,
            metadata={"task_id": "task_parent"},
        )
        with pytest.raises(ToolError, match="max_task_nest_depth"):
            await TaskCreateTool().execute({"prompt": "nested via meta"}, ctx2)
    finally:
        await manager.shutdown()


def test_subagent_runtime_copies_active_task_id(tmp_path) -> None:
    from deepseek_tui.tools.subagent import SubAgentManager, SubAgentRuntime

    manager = SubAgentManager(workspace=tmp_path)
    rt = SubAgentRuntime(
        manager=manager,
        client=object(),
        model="m",
        config=object(),
        workspace=tmp_path,
        active_task_id="task_abc",
    )
    assert rt.with_spawn_depth(1).active_task_id == "task_abc"
    assert rt.child().active_task_id == "task_abc"
    manager.attach_loop_runtime(rt)
    manager.bind_active_task_id("task_xyz")
    assert rt.active_task_id == "task_xyz"


def test_apply_compact_result_merges_summary_into_system_prompt() -> None:
    from deepseek_tui.engine.turn import _apply_compact_result
    from deepseek_tui.protocol.messages import MessageRequest

    req = MessageRequest(
        model="m",
        messages=[Message.user("hi")],
        system_prompt="base",
    )
    _apply_compact_result(
        req,
        ([Message.user("kept")], "<archived_context>sum</archived_context>"),
    )
    assert len(req.messages) == 1
    assert req.messages[0].content[0].text == "kept"  # type: ignore[union-attr]
    assert req.system_prompt is not None
    assert "base" in req.system_prompt
    assert "archived_context" in req.system_prompt


def test_align_insert_index_skips_tool_orphan() -> None:
    from deepseek_tui.protocol.messages import Role

    # Simulate: [user, assistant(tools), tool, tool, user]
    msgs = [
        Message.user("u1"),
        Message.assistant("call"),
        Message.tool_result("t1", "ok"),
        Message.tool_result("t2", "ok"),
        Message.user("u2"),
    ]
    insert_at = 2  # would land between assistant and tool results
    while insert_at > 0 and msgs[insert_at].role == Role.TOOL:
        insert_at -= 1
    assert insert_at == 1
    msgs.insert(insert_at, Message.assistant("seam"))
    # After insert at 1: [user, seam, assistant, tool, tool, user]
    assert msgs[2].role == Role.ASSISTANT
    assert msgs[3].role == Role.TOOL
