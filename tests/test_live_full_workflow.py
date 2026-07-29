"""Live end-to-end workflow: one natural query drives task + subagent + grep.

The parent model must *actively* call ``task_create``, ``agent`` (spawn action)
+ ``task_output``, and ``grep_files`` — no direct tool injection in the test body.

Forces ``volcengine-ark`` / ``glm-5.2`` from user config (top-level provider may
still default to deepseek). Run:

    .venv/bin/python -m pytest tests/test_live_full_workflow.py -m live -v -s

Budget: single test ~120–180s.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from deepseek_tui.client.deepseek import DeepSeekClient
from deepseek_tui.config.loader import ConfigLoader
from deepseek_tui.config.models import Config, FeatureConfig, HooksConfig
from deepseek_tui.engine.orchestrator import Engine
from deepseek_tui.engine.events import (
    TextDeltaEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnCancelledEvent,
    TurnCompleteEvent,
)
from deepseek_tui.engine.handle import AutoApprovalHandler, EngineHandle
from deepseek_tui.tools.approval import ExecPolicyEngine
from deepseek_tui.integrations.hooks import build_hook_dispatcher
from deepseek_tui.tools.runtime import ToolRuntime, create_tool_runtime
from deepseek_tui.tools.task import TaskStatus

_TASK_ID_RE = re.compile(r"task_[a-f0-9]{8}")

PROJECT_ROOT = Path(__file__).resolve().parents[1]

_TIMEOUT_WORKFLOW = 300
_TIMEOUT_TASK_DRAIN = 90
_CORPUS_LINES = "apple\ncherry\nbanana\ncherry\ncherry\n"
_MARKER = "MARKER_LIVE_TEST"

_WORKFLOW_QUERY = f"""请严格按顺序完成以下三步，每一步都必须调用对应工具。全部完成后再回复 WORKFLOW_DONE：

第1步：调用 task_create，prompt="只回复：TASK_DONE"，auto_approve=true。

第2步：调用 agent 工具，action="spawn"，agent_type=explore，prompt="Read WORKSPACE_MARKER.txt and reply with its exact content only"。
spawn 返回 agent_id 后，再调用 task_output（agent_id=<spawn 返回的 id>，block=true）等待子 agent 完成。

第3步：调用 grep_files，pattern="cherry"，path="corpus.txt"，output_mode="count_matches"。

最后回复 WORKFLOW_DONE 并一行总结（需包含 cherry 的匹配行数 3）。"""


@dataclass
class WorkflowTrace:
    tool_calls: list[str] = field(default_factory=list)
    tool_results: list[tuple[str, bool, str]] = field(default_factory=list)
    assistant_text: list[str] = field(default_factory=list)
    turn_ended: str | None = None


def _has_api_key(cfg: Config) -> bool:
    pc = cfg.effective_provider_config()
    return bool(cfg.api_key or pc.api_key)


def _live_config(project_config: Config) -> Config:
    cfg = project_config.model_copy(deep=True)
    # Prefer the user's Volcano GLM setup even when top-level provider is unset.
    if "volcengine-ark" in cfg.providers:
        cfg.provider = "volcengine-ark"
        cfg.model = None
        ark = cfg.providers["volcengine-ark"]
        if ark.model:
            cfg.default_text_model = ark.model
    cfg.hooks = HooksConfig(enabled=False, hooks=[])
    cfg.features = FeatureConfig(
        tasks=True,
        subagents=True,
        mcp=False,
        automations=False,
        plugins=False,
    )
    return cfg


def _prepare_workspace(workspace: Path) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "WORKSPACE_MARKER.txt").write_text(f"{_MARKER}\n", encoding="utf-8")
    (workspace / "corpus.txt").write_text(_CORPUS_LINES, encoding="utf-8")


async def _create_isolated_engine(
    cfg: Config,
    client: DeepSeekClient,
    handle: EngineHandle,
    workspace: Path,
    model: str,
) -> Engine:
    if handle.hooks is None:
        handle.attach_hooks(build_hook_dispatcher(cfg))
    runtime = await create_tool_runtime(
        config=cfg,
        working_directory=workspace,
        task_data_dir=workspace / "task_data",
        subagent_state_path=workspace / "subagents.v1.json",
        start_mcp=False,
    )
    # Engine.create wires attach_loop_runtime (required for agent spawn).
    return await Engine.create(
        handle,
        client,
        config=cfg,
        working_directory=workspace,
        default_model=model,
        exec_policy=ExecPolicyEngine(approval_policy="auto"),
        approval_handler=AutoApprovalHandler(),
        max_tool_round_trips=25,
        tool_runtime=runtime,
        start_mcp=False,
    )


async def _run_workflow_turn(
    engine: Engine,
    handle: EngineHandle,
    query: str,
    *,
    timeout_secs: float,
) -> WorkflowTrace:
    trace = WorkflowTrace()

    async def _engine_loop() -> None:
        await engine.run()

    async def _consume() -> None:
        async for event in handle.events():
            if isinstance(event, ToolCallEvent):
                trace.tool_calls.append(event.tool_call.name)
            elif isinstance(event, ToolResultEvent):
                trace.tool_results.append(
                    (event.tool_name, event.success, event.content or "")
                )
            elif isinstance(event, TextDeltaEvent):
                trace.assistant_text.append(event.text)
            elif isinstance(event, TurnCompleteEvent):
                trace.turn_ended = "complete"
                break
            elif isinstance(event, TurnCancelledEvent):
                trace.turn_ended = "cancelled"
                break

    engine_task = asyncio.create_task(_engine_loop())
    consumer_task = asyncio.create_task(_consume())
    await handle.send_message(content=query)
    try:
        await asyncio.wait_for(consumer_task, timeout=timeout_secs)
    finally:
        engine_task.cancel()
        try:
            await engine_task
        except asyncio.CancelledError:
            pass
    return trace


def _task_id_from_trace(trace: WorkflowTrace) -> str:
    for name, ok, body in trace.tool_results:
        if name != "task_create" or not ok:
            continue
        match = _TASK_ID_RE.search(body)
        if match:
            return match.group(0)
    raise AssertionError(f"could not parse task_id from task_create results: {trace.tool_results}")


async def _wait_for_task_terminal(
    runtime: ToolRuntime,
    task_id: str,
    *,
    timeout_secs: float,
) -> object:
    assert runtime.task_manager is not None
    manager = runtime.task_manager
    deadline = time.monotonic() + timeout_secs
    while time.monotonic() < deadline:
        task = await manager.get_task(task_id)
        if task.status.is_terminal():
            return task
        await asyncio.sleep(0.25)
    task = await manager.get_task(task_id)
    raise AssertionError(
        f"background task {task_id} did not finish within {timeout_secs}s "
        f"(status={task.status.value})"
    )


def _assert_workflow_trace(trace: WorkflowTrace, runtime: ToolRuntime) -> None:
    names = trace.tool_calls
    assert "task_create" in names, f"model never called task_create; got {names}"
    assert "agent" in names, f"model never called agent; got {names}"
    assert "grep_files" in names, f"model never called grep_files; got {names}"

    successes = {name for name, ok, _ in trace.tool_results if ok}
    assert "task_create" in successes
    assert "agent" in successes
    assert "grep_files" in successes

    final_text = "".join(trace.assistant_text)
    assert "WORKFLOW_DONE" in final_text, final_text[-800:]
    assert _MARKER in final_text or any(_MARKER in body for _, _, body in trace.tool_results)
    grep_bodies = [body for name, _, body in trace.tool_results if name == "grep_files"]
    assert any("3" in body for body in grep_bodies) or "3" in final_text

    assert trace.turn_ended == "complete", trace.turn_ended

    assert runtime.task_manager is not None
    assert runtime.subagent_manager is not None


@pytest.fixture(scope="module")
def project_config() -> Config:
    cfg = ConfigLoader().load(workspace=PROJECT_ROOT)
    if not _has_api_key(_live_config(cfg)):
        pytest.skip("no API key for volcengine-ark / configured provider")
    return cfg


@pytest.fixture(scope="module")
def live_model(project_config: Config) -> str:
    cfg = _live_config(project_config)
    pc = cfg.effective_provider_config()
    return pc.model or cfg.model or cfg.default_text_model


@pytest.mark.live
class TestLiveFullWorkflow:
    async def test_natural_query_invokes_task_subagent_grep(
        self,
        project_config: Config,
        live_model: str,
        tmp_path: Path,
    ) -> None:
        """One user query orchestrates durable task, sub-agent, and grep_files."""
        cfg = _live_config(project_config)
        workspace = tmp_path / "workflow_ws"
        _prepare_workspace(workspace)

        client = DeepSeekClient.from_config(cfg)
        handle = EngineHandle()
        engine = await _create_isolated_engine(cfg, client, handle, workspace, live_model)
        runtime = engine.tool_runtime
        assert runtime is not None

        try:
            trace = await _run_workflow_turn(
                engine,
                handle,
                _WORKFLOW_QUERY,
                timeout_secs=_TIMEOUT_WORKFLOW,
            )
            _assert_workflow_trace(trace, runtime)

            task_id = _task_id_from_trace(trace)
            finished = await _wait_for_task_terminal(
                runtime,
                task_id,
                timeout_secs=_TIMEOUT_TASK_DRAIN,
            )
            assert finished.status is TaskStatus.COMPLETED
            assert finished.result_summary
            assert "TASK_DONE" in finished.result_summary.upper()

            assert runtime.task_manager is not None
            summaries = await runtime.task_manager.list_tasks(limit=5)
            assert any(task_id in s.id for s in summaries)
        finally:
            await engine.shutdown()
            await client.close()


@pytest.fixture(scope="module", autouse=True)
def _live_workflow_budget() -> None:
    started = time.monotonic()
    yield
    elapsed = time.monotonic() - started
    if elapsed > 420.0:
        pytest.fail(f"live full workflow module exceeded 420s budget ({elapsed:.1f}s)")
