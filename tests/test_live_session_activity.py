"""Live tests: subagent handoff, task activity, RLM progress with real API.

Uses ``.deepseek/config.toml``. **Opt-in only** (real API + memory cost):

    DEEPSEEK_RUN_LIVE=1 .venv/bin/python -m pytest tests/test_live_session_activity.py -m live -v -s

Skipped by default so CI/local ``pytest`` does not spawn long-running engines.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("DEEPSEEK_RUN_LIVE") != "1",
    reason="set DEEPSEEK_RUN_LIVE=1 to run live API tests",
)

from deepseek_tui.client.deepseek import DeepSeekClient
from deepseek_tui.config.loader import ConfigLoader
from deepseek_tui.config.models import Config, FeatureConfig, HooksConfig
from deepseek_tui.engine.engine import Engine
from deepseek_tui.engine.events import (
    SessionActivityEvent,
    StatusEvent,
    SubAgentMailboxEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnCompleteEvent,
)
from deepseek_tui.engine.handle import AutoApprovalHandler, EngineHandle
from deepseek_tui.hooks.build import build_hook_dispatcher
from deepseek_tui.tools.subagent.mailbox import MailboxMessageKind

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_TIMEOUT_SUBAGENT = 120
_TIMEOUT_TASK = 90
_TIMEOUT_RLM = 120


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


def _live_cfg(project_config: Config) -> Config:
    cfg = project_config.model_copy(deep=True)
    cfg.hooks = HooksConfig(enabled=False, hooks=[])
    cfg.features = FeatureConfig(tasks=True, subagents=True, mcp=False)
    return cfg


async def _run_engine_query(
    cfg: Config,
    client: DeepSeekClient,
    workspace: Path,
    model: str,
    query: str,
    *,
    timeout: float,
) -> list[object]:
    handle = EngineHandle()
    handle.attach_hooks(build_hook_dispatcher(cfg))
    engine = await Engine.create(
        handle=handle,
        client=client,
        config=cfg,
        working_directory=workspace,
        default_model=model,
        approval_handler=AutoApprovalHandler(),
        task_data_dir=workspace / ".deepseek" / "tasks",
    )
    events: list[object] = []
    engine_task = asyncio.create_task(engine.run())

    async def _collect() -> None:
        await handle.send_message(content=query)
        deadline = time.monotonic() + timeout
        turn_done_at: float | None = None
        while time.monotonic() < deadline:
            try:
                ev = await asyncio.wait_for(handle.events().__anext__(), timeout=2.0)
            except (asyncio.TimeoutError, StopAsyncIteration):
                if engine_task.done():
                    break
                if turn_done_at is not None and time.monotonic() - turn_done_at > 3.0:
                    break
                continue
            events.append(ev)
            if isinstance(ev, TurnCompleteEvent):
                turn_done_at = time.monotonic()
            elif turn_done_at is not None and time.monotonic() - turn_done_at > 3.0:
                break

    try:
        await asyncio.wait_for(_collect(), timeout=timeout)
    except asyncio.TimeoutError:
        pass
    finally:
        handle.cancel_event.set()
        await handle.cancel("test_done")
        engine_task.cancel()
        try:
            await asyncio.wait_for(engine_task, timeout=5.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            pass
        await engine.shutdown_session()
        handle.drain_events()

    return events


@pytest.mark.live
class TestLiveSessionActivity:
    async def test_subagent_spawn_handoff_and_mailbox(
        self, project_config: Config, live_model: str, tmp_path: Path
    ) -> None:
        marker = "SESSION_ACTIVITY_MARKER"
        (tmp_path / "probe.txt").write_text(f"{marker}\n", encoding="utf-8")
        cfg = _live_cfg(project_config)
        client = DeepSeekClient.from_config(cfg)

        query = (
            f"Call agent_spawn with type=explore and prompt="
            f"'Read probe.txt and reply with exactly: {marker}'. "
            "Do NOT call agent_wait. After spawn returns, reply SPAWNED_ONLY."
        )
        events = await _run_engine_query(
            cfg, client, tmp_path, live_model, query, timeout=_TIMEOUT_SUBAGENT
        )

        names = [e.tool_call.name for e in events if isinstance(e, ToolCallEvent)]
        assert "agent_spawn" in names, f"expected agent_spawn, got {names}"

        statuses = [e.message for e in events if isinstance(e, StatusEvent)]
        assert any("Waiting on" in s or "sub-agent completion" in s for s in statuses), (
            f"expected #756 wait/resume status, got {statuses}"
        )

        mailbox_kinds = [
            e.message.kind
            for e in events
            if isinstance(e, SubAgentMailboxEvent)
        ]
        assert MailboxMessageKind.STARTED in mailbox_kinds or MailboxMessageKind.TOOL_CALL_STARTED in mailbox_kinds, (
            f"expected mailbox events, got {mailbox_kinds}"
        )

    async def test_task_create_background_activity(
        self, project_config: Config, live_model: str, tmp_path: Path
    ) -> None:
        cfg = _live_cfg(project_config)
        client = DeepSeekClient.from_config(cfg)
        query = (
            'Call task_create with prompt="Reply TASK_OK only" and auto_approve=true. '
            "Then reply TASK_QUEUED."
        )
        events = await _run_engine_query(
            cfg, client, tmp_path, live_model, query, timeout=_TIMEOUT_TASK
        )

        names = [e.tool_call.name for e in events if isinstance(e, ToolCallEvent)]
        assert "task_create" in names

        activity = [e for e in events if isinstance(e, SessionActivityEvent)]
        turn = next((e for e in events if isinstance(e, TurnCompleteEvent)), None)
        assert turn is not None
        saw_running = turn.running_tasks >= 1 or any(
            a.running_tasks >= 1 for a in activity
        )
        if not saw_running:
            task_results = [
                e
                for e in events
                if isinstance(e, ToolResultEvent) and e.tool_name == "task_create"
            ]
            assert task_results and task_results[0].success
            assert "task_" in task_results[0].content
        else:
            assert saw_running

    async def test_rlm_progress_events(
        self, project_config: Config, live_model: str, tmp_path: Path
    ) -> None:
        """RLM progress via ToolContext callback (avoids hung full-engine turn)."""
        from deepseek_tui.engine.events import RlmProgressEvent as RlmEv
        from deepseek_tui.tools.context import ToolContext
        from deepseek_tui.tools.rlm.tool import RlmTool

        (tmp_path / "tiny.txt").write_text("alpha\nbeta\nalpha\n", encoding="utf-8")
        client = DeepSeekClient.from_config(project_config)
        tool = RlmTool(client=client, root_model=live_model)
        progress: list[RlmEv] = []

        def _on_progress(iteration: int, summary: str, rpc_count: int = 0) -> None:
            progress.append(
                RlmEv(iteration=iteration, summary=summary, rpc_count=rpc_count)
            )

        ctx = ToolContext(working_directory=tmp_path)
        ctx.metadata["rlm_progress_cb"] = _on_progress

        async def _run() -> None:
            result = await tool.execute(
                {
                    "task": (
                        "Count lines containing alpha using repl + llm_query, "
                        "then FINAL with the number."
                    ),
                    "file_path": "tiny.txt",
                },
                ctx,
            )
            assert result.success is True
            assert len(progress) >= 1, f"expected progress callbacks, got {len(progress)}"

        try:
            await asyncio.wait_for(_run(), timeout=_TIMEOUT_RLM)
        finally:
            await client.close()
