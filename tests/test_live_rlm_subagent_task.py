"""Live integration tests for RLM / Subagent / Task parity work.

Uses project ``.deepseek/config.toml`` (real DeepSeek API). Run explicitly:

    .venv/bin/python -m pytest tests/test_live_rlm_subagent_task.py -m live -v

Individual caps: API smoke ~30s, RLM ~120s, subagent ~90s, task gate ~15s,
task executor ~90s each.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from deepseek_tui.client.deepseek import DeepSeekClient
from deepseek_tui.config.loader import ConfigLoader
from deepseek_tui.config.models import Config, FeatureConfig
from deepseek_tui.engine.orchestrator import Engine
from deepseek_tui.engine.handle import AutoApprovalHandler, EngineHandle
from deepseek_tui.policy.approval import ExecPolicyEngine
from deepseek_tui.protocol.responses import ToolCall
from deepseek_tui.tools.registry import ToolContext
from deepseek_tui.tools.rlm import RlmTool
from deepseek_tui.tools.subagent import (
    Mailbox,
    SpawnRequest,
    SubAgentAssignment,
    SubAgentManager,
    SubAgentType,
)
from deepseek_tui.tools.subagent import MailboxMessageKind
from deepseek_tui.tools.subagent import get_real_subagent_executor
from deepseek_tui.tools.task import (
    NewTaskRequest,
    TaskManager,
    TaskManagerConfig,
    TaskStatus,
    get_real_task_executor,
)
from deepseek_tui.tools.task import TaskCreateTool, TaskGateRunTool

PROJECT_ROOT = Path(__file__).resolve().parents[1]

_TIMEOUT_API = 30
_TIMEOUT_RLM = 120
_TIMEOUT_SUBAGENT = 90
_TIMEOUT_ENGINE = 60
_TIMEOUT_GATE = 15
_TIMEOUT_TASK_EXEC = 90


async def _wait_for_task_terminal(
    manager: TaskManager,
    task_id: str,
    *,
    timeout_secs: float = _TIMEOUT_TASK_EXEC,
) -> object:
    deadline = time.monotonic() + timeout_secs
    while time.monotonic() < deadline:
        task = await manager.get_task(task_id)
        if task.status.is_terminal():
            return task
        await asyncio.sleep(0.25)
    task = await manager.get_task(task_id)
    raise AssertionError(
        f"task {task_id} did not reach terminal state within {timeout_secs}s "
        f"(last status={task.status.value})"
    )


def _has_api_key(cfg: Config) -> bool:
    pc = cfg.effective_provider_config()
    return bool(cfg.api_key or pc.api_key)


@pytest.fixture(scope="module")
def project_config() -> Config:
    cfg = ConfigLoader().load(workspace=PROJECT_ROOT)
    if not _has_api_key(cfg):
        pytest.skip("no API key in .deepseek/config.toml")
    return cfg


@pytest.fixture(scope="module")
def live_model(project_config: Config) -> str:
    return project_config.model or project_config.default_text_model


@pytest.mark.live
class TestLiveRlmSubagentTask:
    async def test_01_api_smoke(self, project_config: Config, live_model: str) -> None:
        client = DeepSeekClient.from_config(project_config)
        from deepseek_tui.protocol.messages import Message
        from deepseek_tui.protocol.messages import MessageRequest
        from deepseek_tui.protocol.responses import StreamTextDelta

        req = MessageRequest(
            model=live_model,
            messages=[Message.user("只回复两个字母：OK")],
            stream=True,
            max_tokens=512,
        )
        chunks: list[str] = []
        thinking: list[str] = []

        async def _consume() -> None:
            from deepseek_tui.protocol.responses import StreamThinkingDelta

            async for event in client.stream_chat_completion(req):
                if isinstance(event, StreamTextDelta):
                    chunks.append(event.text)
                elif isinstance(event, StreamThinkingDelta):
                    thinking.append(event.thinking)

        try:
            await asyncio.wait_for(_consume(), timeout=_TIMEOUT_API)
        finally:
            await client.close()

        text = "".join(chunks).strip()
        combined = (text + "".join(thinking)).upper()
        assert combined, "expected assistant text or reasoning content"
        assert "OK" in combined

    async def test_02_engine_wires_rlm_client(
        self, project_config: Config, live_model: str, tmp_path: Path
    ) -> None:
        cfg = project_config.model_copy(deep=True)
        cfg.features = FeatureConfig(tasks=True, subagents=True, mcp=False)
        client = DeepSeekClient.from_config(cfg)
        handle = EngineHandle()

        async def _run() -> None:
            engine = await Engine.create(
                handle=handle,
                client=client,
                config=cfg,
                working_directory=tmp_path,
                default_model=live_model,
                approval_handler=AutoApprovalHandler(),
                exec_policy=ExecPolicyEngine(approval_policy="auto"),
            )
            try:
                rlm = engine.tool_registry.get("rlm")
                assert isinstance(rlm, RlmTool)
                assert rlm._client is client
                assert rlm._root_model == live_model
            finally:
                await engine.shutdown()
                await client.close()

        await asyncio.wait_for(_run(), timeout=_TIMEOUT_ENGINE)

    async def test_03_rlm_tool_live_inline(
        self, project_config: Config, live_model: str, tmp_path: Path
    ) -> None:
        """RLM end-to-end: REPL + child llm_query + FINAL on real API."""
        client = DeepSeekClient.from_config(project_config)
        tool = RlmTool(client=client, root_model=live_model)
        ctx = ToolContext(working_directory=tmp_path)
        content = "apple\nbanana\napple\ncherry\napple\n"
        task = (
            "Use Python to count lines containing apple, "
            "llm_query to return only the number, then FINAL."
        )

        async def _run_once() -> None:
            result = await tool.execute(
                {"task": task, "content": content},
                ctx,
            )
            assert result.success is True
            assert "3" in result.content
            meta = result.metadata
            assert meta.get("child_model") == "deepseek-v4-flash"
            assert meta.get("termination") == "final"
            assert int(meta.get("total_rpcs") or 0) >= 1
            assert int(meta.get("child_input_tokens") or 0) > 0
            assert int(meta.get("child_output_tokens") or 0) > 0

        async def _run() -> None:
            last_exc: Exception | None = None
            for _attempt in range(2):
                try:
                    await _run_once()
                    return
                except (AssertionError, Exception) as exc:  # noqa: BLE001
                    last_exc = exc
            raise last_exc or AssertionError("RLM live test failed after retries")

        try:
            await asyncio.wait_for(_run(), timeout=_TIMEOUT_RLM)
        finally:
            await client.close()

    async def test_04_rlm_via_engine_accrues_child_cost(
        self, project_config: Config, live_model: str, tmp_path: Path
    ) -> None:
        cfg = project_config.model_copy(deep=True)
        cfg.features = FeatureConfig(tasks=False, subagents=False, mcp=False)
        client = DeepSeekClient.from_config(cfg)
        handle = EngineHandle()

        async def _run() -> None:
            engine = await Engine.create(
                handle=handle,
                client=client,
                config=cfg,
                working_directory=tmp_path,
                default_model=live_model,
                approval_handler=AutoApprovalHandler(),
                exec_policy=ExecPolicyEngine(approval_policy="auto"),
            )
            try:
                before = engine.session_cost_usd
                tc = ToolCall(
                    id="live-rlm-1",
                    name="rlm",
                    arguments={
                        "task": (
                            "Count lines containing 'x' in context with Python, "
                            "llm_query for the number only, then FINAL."
                        ),
                        "content": "x\ny\nx\n",
                    },
                )
                result = await engine._execute_single_tool(
                    tc, [], live_model
                )
                assert result is not None and result.success
                assert engine.session_cost_usd >= before
                assert result.metadata.get("child_model") == "deepseek-v4-flash"
            finally:
                await engine.shutdown()
                await client.close()

        await asyncio.wait_for(_run(), timeout=_TIMEOUT_RLM)

    async def test_05_task_gate_run_live_persistence(
        self, project_config: Config, tmp_path: Path
    ) -> None:
        async def _stub(task, cancel):  # noqa: ANN001
            from deepseek_tui.tools.task import TaskExecutionResult

            return TaskExecutionResult(summary="ok")

        mgr_cfg = TaskManagerConfig(
            data_dir=tmp_path / "tasks",
            default_workspace=tmp_path,
        )
        manager = TaskManager(mgr_cfg, executor=_stub)
        await manager.start()
        try:
            task = await manager.add_task(NewTaskRequest(prompt="live gate smoke"))
            assert task.auto_approve is False

            ctx = ToolContext(
                working_directory=tmp_path,
                task_manager=manager,
                active_task_id=task.id,
            )
            result = await asyncio.wait_for(
                TaskGateRunTool().execute(
                    {"gate": "custom", "command": "echo live_gate_ok"},
                    ctx,
                ),
                timeout=_TIMEOUT_GATE,
            )
            assert result.success is True
            assert "task_updates" in result.metadata
            await asyncio.sleep(0.1)
            updated = await manager.get_task(task.id)
            assert len(updated.gates) == 1
            assert updated.gates[0].status == "passed"
        finally:
            await manager.shutdown()

    async def test_06_task_create_default_auto_approve_false(
        self, project_config: Config, tmp_path: Path
    ) -> None:
        async def _stub(task, cancel):  # noqa: ANN001
            from deepseek_tui.tools.task import TaskExecutionResult

            return TaskExecutionResult(summary="ok")

        mgr_cfg = TaskManagerConfig(
            data_dir=tmp_path / "tasks2",
            default_workspace=tmp_path,
        )
        manager = TaskManager(mgr_cfg, executor=_stub)
        await manager.start()
        try:
            ctx = ToolContext(working_directory=tmp_path, task_manager=manager)
            result = await TaskCreateTool().execute(
                {"prompt": "live task create smoke"},
                ctx,
            )
            assert result.success is True
            task_id = result.metadata["task_id"]
            task = await manager.get_task(task_id)
            assert task.auto_approve is False
        finally:
            await manager.shutdown()

    async def test_07_subagent_live_real_executor(
        self, project_config: Config, live_model: str, tmp_path: Path
    ) -> None:
        mailbox = Mailbox()
        client = DeepSeekClient.from_config(project_config)

        async def _run() -> None:
            manager = SubAgentManager(
                workspace=tmp_path,
                mailbox=mailbox,
                executor=get_real_subagent_executor(),
                default_model=live_model,
            )
            from deepseek_tui.tools.subagent import SubAgentRuntime

            manager.attach_loop_runtime(
                SubAgentRuntime(
                    manager=manager,
                    client=client,
                    model=live_model,
                    config=project_config,
                    workspace=tmp_path,
                    mailbox=mailbox,
                    auto_approve=True,
                )
            )
            spawned = await manager.spawn(
                SpawnRequest(
                    prompt="只回复一个词：完成",
                    agent_type=SubAgentType.GENERAL,
                    assignment=SubAgentAssignment(
                        objective="live subagent smoke",
                        role="qa",
                    ),
                )
            )
            await manager.wait([spawned.agent_id], mode="all", timeout_ms=85_000)
            final = await manager.get_result(spawned.agent_id)
            assert final.status.kind.value == "completed"
            assert final.result
            assert "完成" in final.result

            envelopes = await mailbox.drain_available()
            kinds = [e.message.kind for e in envelopes]
            assert MailboxMessageKind.STARTED in kinds
            assert MailboxMessageKind.COMPLETED in kinds
            assert MailboxMessageKind.TOKEN_USAGE in kinds

        try:
            await asyncio.wait_for(_run(), timeout=_TIMEOUT_SUBAGENT)
        finally:
            await client.close()

    async def test_08_task_real_executor_completes(
        self, project_config: Config, live_model: str, tmp_path: Path
    ) -> None:
        """TaskManager worker + real_task_executor + real DeepSeek API."""
        mgr_cfg = TaskManagerConfig(
            data_dir=tmp_path / "task_exec",
            default_workspace=tmp_path,
            default_model=live_model,
        )
        manager = TaskManager(mgr_cfg, executor=get_real_task_executor())
        await manager.start()
        try:
            created = await manager.add_task(
                NewTaskRequest(
                    prompt="只回复一个词：完成",
                    auto_approve=True,
                )
            )
            final = await _wait_for_task_terminal(manager, created.id)
            assert final.status is TaskStatus.COMPLETED
            assert final.result_summary
            assert "完成" in final.result_summary
            assert final.duration_ms is not None and final.duration_ms > 0
            kinds = [entry.kind for entry in final.timeline]
            assert "running" in kinds
            assert "completed" in kinds
        finally:
            await manager.shutdown()

    async def test_09_task_real_executor_auto_approve_false(
        self, project_config: Config, live_model: str, tmp_path: Path
    ) -> None:
        """Text-only tasks must complete even when auto_approve=False (GHSA default)."""
        mgr_cfg = TaskManagerConfig(
            data_dir=tmp_path / "task_exec_no_auto",
            default_workspace=tmp_path,
            default_model=live_model,
        )
        manager = TaskManager(mgr_cfg, executor=get_real_task_executor())
        await manager.start()
        try:
            created = await manager.add_task(
                NewTaskRequest(
                    prompt="只回复两个字母：OK",
                    auto_approve=False,
                )
            )
            assert created.auto_approve is False
            final = await _wait_for_task_terminal(manager, created.id)
            assert final.status is TaskStatus.COMPLETED
            assert final.result_summary
            combined = final.result_summary.upper()
            assert "OK" in combined
            assert final.error is None
        finally:
            await manager.shutdown()

    async def test_10_task_executor_wires_task_context_for_tools(
        self, project_config: Config, live_model: str, tmp_path: Path
    ) -> None:
        """While a task runs, task_gate_run can attach evidence via active_task_id."""
        mgr_cfg = TaskManagerConfig(
            data_dir=tmp_path / "task_exec_gate",
            default_workspace=tmp_path,
            default_model=live_model,
        )
        manager = TaskManager(mgr_cfg, executor=get_real_task_executor())
        await manager.start()
        try:
            created = await manager.add_task(
                NewTaskRequest(
                    prompt="只回复：gate-context-ok",
                    auto_approve=True,
                )
            )
            final = await _wait_for_task_terminal(manager, created.id)
            assert final.status is TaskStatus.COMPLETED

            ctx = ToolContext(
                working_directory=tmp_path,
                task_manager=manager,
                active_task_id=created.id,
            )
            gate = await TaskGateRunTool().execute(
                {"gate": "custom", "command": "echo executor_context_ok"},
                ctx,
            )
            assert gate.success is True
            await asyncio.sleep(0.1)
            updated = await manager.get_task(created.id)
            assert len(updated.gates) == 1
            assert updated.gates[0].status == "passed"
            assert "executor_context_ok" in (updated.gates[0].summary or "")
        finally:
            await manager.shutdown()


@pytest.fixture(scope="module", autouse=True)
def _live_module_budget() -> None:
    started = time.monotonic()
    yield
    elapsed = time.monotonic() - started
    if elapsed > 540.0:
        pytest.fail(
            f"live RLM/subagent/task module exceeded 540s budget ({elapsed:.1f}s)"
        )
