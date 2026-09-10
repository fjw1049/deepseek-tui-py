"""Behavior regressions for the first, deliberately limited optimization batch."""

import asyncio
from contextlib import suppress

import pytest

from deepseek_tui.client.base import LLMClient, RetryConfig
from deepseek_tui.config.models import Config
from deepseek_tui.protocol.responses import StreamDone, StreamTextDelta
from deepseek_tui.tools.approval import build_approval_key
from deepseek_tui.tools.registry import ToolContext
from deepseek_tui.tools.subagent import (
    Mailbox,
    SpawnRequest,
    SubAgentAssignment,
    SubAgentManager,
    SubAgentRuntime,
    SubAgentType,
    get_real_subagent_executor,
)
from deepseek_tui.tools.task import NewTaskRequest, TaskManager, TaskManagerConfig
from deepseek_tui.tools.task.tools import TaskCreateTool


async def test_task_create_uses_each_session_workspace(tmp_path):
    manager = TaskManager(
        TaskManagerConfig(data_dir=tmp_path / "tasks", default_workspace=tmp_path)
    )
    for name in ("project-a", "project-b"):
        workspace = tmp_path / name
        workspace.mkdir()
        result = await TaskCreateTool().execute(
            {"prompt": "inspect project"},
            ToolContext(working_directory=workspace, task_manager=manager),
        )
        task = await manager.get_task(result.metadata["task_id"])
        assert task.workspace == str(workspace.resolve())
    internal = await manager.add_task(NewTaskRequest(prompt="internal"))
    assert internal.workspace == str(tmp_path)


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("git branch -d topic", "git branch -D topic"),
        ('printf "A"', 'printf "a"'),
        ('printf "a  b"', 'printf "a b"'),
        ("echo " + "x" * 300 + "A", "echo " + "x" * 300 + "a"),
    ],
)
def test_shell_approval_preserves_command_bytes(first, second):
    assert build_approval_key("exec_shell", {"command": first}) != build_approval_key(
        "exec_shell", {"command": second}
    )


def test_shell_approval_scopes_actual_workspace(tmp_path):
    args = {"command": "make install"}
    first = build_approval_key("exec_shell", args, working_directory=tmp_path / "a")
    assert first != build_approval_key("exec_shell", args, working_directory=tmp_path / "b")
    assert first == build_approval_key("exec_shell", dict(args), working_directory=tmp_path / "a")


class _InputClient(LLMClient):
    def __init__(self, first_summary, block_second):
        super().__init__(RetryConfig(base_delay=0, max_delay=0))
        self.first_summary = first_summary
        self.block_second = block_second
        self.requests = []
        self.started = [asyncio.Event(), asyncio.Event()]
        self.release = asyncio.Event()

    async def stream_chat_completion(self, request):
        index = len(self.requests)
        self.requests.append(request.model_copy(deep=True))
        if index < 2:
            self.started[index].set()
        if index == 0:
            await self.release.wait()
        if index == 1 and self.block_second:
            await asyncio.Event().wait()
        text = "### SUMMARY\nInspection complete: no changes required."
        if index == 0 and not self.first_summary:
            text = "I will continue checking."
        yield StreamTextDelta(text=text)
        yield StreamDone()


@pytest.mark.parametrize(
    ("first_summary", "cancel_round"), [(False, None), (True, None), (False, 0), (False, 1)]
)
async def test_running_input_delivered_once_and_survives_cancel(
    tmp_path, monkeypatch, first_summary, cancel_round
):
    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    mailbox = Mailbox()
    client = _InputClient(first_summary, cancel_round == 1)
    manager = SubAgentManager(
        workspace=tmp_path,
        mailbox=mailbox,
        executor=get_real_subagent_executor(),
        default_model="deepseek-chat",
    )
    manager.attach_loop_runtime(
        SubAgentRuntime(
            manager=manager,
            client=client,
            model="deepseek-chat",
            config=Config(),
            workspace=tmp_path,
            mailbox=mailbox,
            auto_approve=True,
        )
    )
    try:
        spawned = await manager.spawn(
            SpawnRequest(
                prompt="Inspect project",
                agent_type=SubAgentType.EXPLORE,
                assignment=SubAgentAssignment(objective="Inspect project", role="qa"),
            )
        )
        await asyncio.wait_for(client.started[0].wait(), 5)
        await manager.send_input(spawned.agent_id, "EXTRA-FIRST")
        await manager.send_input(spawned.agent_id, "EXTRA-SECOND")
        if cancel_round != 0:
            client.release.set()
        if cancel_round == 1:
            await asyncio.wait_for(client.started[1].wait(), 5)
            assert client.requests[1].model_dump_json().count("EXTRA-FIRST") == 1
        if cancel_round is not None:
            task = manager._agents[spawned.agent_id].task
            await manager.cancel(spawned.agent_id)
            with suppress(asyncio.CancelledError):
                await task
            client.block_second = False
            await manager.resume(spawned.agent_id)
        await manager.wait([spawned.agent_id], mode="all", timeout_ms=10000)
        assert len(client.requests) >= 2
        serialized = client.requests[-1].model_dump_json()
        assert serialized.count("EXTRA-FIRST") == 1
        assert serialized.count("EXTRA-SECOND") == 1
        assert serialized.index("EXTRA-FIRST") < serialized.index("EXTRA-SECOND")
    finally:
        await manager.shutdown()


async def test_actual_approval_gate_reprompts_on_command_or_directory_change(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from deepseek_tui.engine.orchestrator.tooling import ToolExecutionMixin
    from deepseek_tui.protocol.responses import ToolCall
    from deepseek_tui.tools.approval import (
        ApprovalCache,
        ApprovalDecision,
        ApprovalRequest,
        RiskLevel,
        ToolCategory,
    )

    gate = ToolExecutionMixin()
    gate.tool_context = ToolContext(working_directory=tmp_path / "a")
    gate.approval_cache = ApprovalCache()
    gate.handle = SimpleNamespace(emit=AsyncMock())
    gate.approval_handler = SimpleNamespace(
        auto_approve_enabled=AsyncMock(return_value=False),
        request_approval=AsyncMock(return_value=ApprovalDecision.APPROVED_SESSION),
    )
    for index, (command, directory, prompts) in enumerate(
        [
            ("git branch -d topic", "a", 1),
            ("git branch -d topic", "a", 1),
            ("git branch -D topic", "a", 2),
            ("git branch -D topic", "b", 3),
            ("git branch -D topic", "b", 3),
        ]
    ):
        gate.tool_context.working_directory = tmp_path / directory
        args = {"command": command}
        req = ApprovalRequest(
            tool_name="exec_shell",
            risk_level=RiskLevel.MEDIUM,
            category=ToolCategory.CODE_EXEC,
            reason="Run command",
        )
        denied = await gate._handle_approval_flow(
            ToolCall(id=str(index), name="exec_shell", arguments=args), req
        )
        assert not denied
        assert gate.approval_handler.request_approval.await_count == prompts
        if req.approval_key:
            assert req.approval_key == str(
                build_approval_key("exec_shell", args, working_directory=tmp_path / directory)
            )


@pytest.mark.parametrize("flag", ["pty", "background"])
def test_shell_execution_mode_has_separate_approval(flag):
    assert build_approval_key("exec_shell", {"command": "make"}) != build_approval_key(
        "exec_shell", {"command": "make", flag: True}
    )


async def test_explicit_task_workspace_keeps_boundary_checks(tmp_path):
    from deepseek_tui.tools.registry import ToolError

    workspace = tmp_path / "project"
    workspace.mkdir()
    (workspace / "child").mkdir()
    (workspace / "escape").symlink_to(tmp_path, target_is_directory=True)
    manager = TaskManager(
        TaskManagerConfig(data_dir=tmp_path / "tasks", default_workspace=tmp_path)
    )
    context = ToolContext(working_directory=workspace, task_manager=manager)
    result = await TaskCreateTool().execute({"prompt": "inspect", "workspace": "child"}, context)
    task = await manager.get_task(result.metadata["task_id"])
    assert task.workspace == str((workspace / "child").resolve())
    for outside in ("..", "escape"):
        with pytest.raises(ToolError, match="inside the current session workspace"):
            await TaskCreateTool().execute({"prompt": "inspect", "workspace": outside}, context)
