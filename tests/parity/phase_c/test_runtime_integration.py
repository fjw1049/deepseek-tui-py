"""Integration tests for :func:`create_tool_runtime` wiring.

These tests guard against "island" modules — they ensure every Stage 3
manager is actually reachable via the registry dispatch path, not just
wired in isolation inside its own unit test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deepseek_tui.config.models import Config
from deepseek_tui.tools.runtime import create_tool_runtime


@pytest.fixture
def cfg_default() -> Config:
    return Config()


class TestRuntimeWiring:
    async def test_registry_has_task_and_subagent_tools(
        self, tmp_path: Path, cfg_default: Config
    ) -> None:
        runtime = await create_tool_runtime(
            config=cfg_default,
            working_directory=tmp_path,
            task_data_dir=tmp_path / "task_data",
            subagent_state_path=tmp_path / "sub.json",
        )
        try:
            names = set(runtime.registry.names())
            # All 11 task tools registered
            for n in (
                "task_create",
                "task_list",
                "task_read",
                "task_cancel",
                "task_gate_run",
                "task_shell_start",
                "task_shell_wait",
                "pr_attempt_record",
                "pr_attempt_list",
                "pr_attempt_read",
                "pr_attempt_preflight",
            ):
                assert n in names, f"missing tool: {n}"
            # All 10 subagent tools registered
            for n in (
                "agent_spawn",
                "agent_result",
                "agent_cancel",
                "close_agent",
                "resume_agent",
                "agent_list",
                "agent_send_input",
                "agent_assign",
                "agent_wait",
                "delegate_to_agent",
            ):
                assert n in names, f"missing tool: {n}"
        finally:
            await runtime.shutdown()

    async def test_task_create_goes_through_registry_to_manager(
        self, tmp_path: Path, cfg_default: Config
    ) -> None:
        runtime = await create_tool_runtime(
            config=cfg_default,
            working_directory=tmp_path,
            task_data_dir=tmp_path / "task_data",
            subagent_state_path=tmp_path / "sub.json",
        )
        try:
            tool = runtime.registry.get("task_create")
            result = await tool.execute(
                {"prompt": "wired via registry"}, runtime.context
            )
            assert result.success
            task_id = result.metadata["task_id"]
            # Manager must know about the task — direct path proves the
            # registry dispatch hit the real manager, not a stub.
            assert runtime.task_manager is not None
            seen = await runtime.task_manager.get_task(task_id)
            assert seen.id == task_id
        finally:
            await runtime.shutdown()

    async def test_agent_spawn_goes_through_registry_to_manager(
        self, tmp_path: Path, cfg_default: Config
    ) -> None:
        runtime = await create_tool_runtime(
            config=cfg_default,
            working_directory=tmp_path,
            task_data_dir=tmp_path / "task_data",
            subagent_state_path=tmp_path / "sub.json",
        )
        try:
            tool = runtime.registry.get("agent_spawn")
            result = await tool.execute(
                {"prompt": "explore", "type": "explore"}, runtime.context
            )
            assert result.success
            agent_id = result.metadata["agent_id"]
            assert runtime.subagent_manager is not None
            listed = runtime.subagent_manager.list_agents()
            assert any(a.agent_id == agent_id for a in listed)
        finally:
            await runtime.shutdown()

    async def test_task_shell_start_wait_end_to_end(
        self, tmp_path: Path, cfg_default: Config
    ) -> None:
        """End-to-end: task created → task_shell_start → task_shell_wait.

        Regression guard for the Stage 3.4 integration. Validates that
        task_shell tools use the exec_shell pty path and record back
        onto the task's artifacts list.
        """
        runtime = await create_tool_runtime(
            config=cfg_default,
            working_directory=tmp_path,
            task_data_dir=tmp_path / "task_data",
            subagent_state_path=tmp_path / "sub.json",
        )
        try:
            task_create = runtime.registry.get("task_create")
            task_r = await task_create.execute(
                {"prompt": "e2e-shell"}, runtime.context
            )
            task_id = task_r.metadata["task_id"]

            start = runtime.registry.get("task_shell_start")
            started = await start.execute(
                {"id": task_id, "command": "echo wired", "pty": False},
                runtime.context,
            )
            process_id = started.metadata["process_id"]

            wait = runtime.registry.get("task_shell_wait")
            waited = await wait.execute(
                {"process_id": process_id, "task_id": task_id},
                runtime.context,
            )
            assert waited.success
            assert "wired" in waited.content

            # Artifact recorded on the task
            assert runtime.task_manager is not None
            task = await runtime.task_manager.get_task(task_id)
            assert any("shell[" in a.label for a in task.artifacts)
        finally:
            await runtime.shutdown()

    async def test_features_tasks_false_skips_task_tools(
        self, tmp_path: Path
    ) -> None:
        cfg = Config()
        cfg.features.tasks = False
        runtime = await create_tool_runtime(
            config=cfg,
            working_directory=tmp_path,
            subagent_state_path=tmp_path / "sub.json",
        )
        try:
            assert runtime.task_manager is None
            assert "task_create" not in runtime.registry.names()
            # Subagent still on by default
            assert "agent_spawn" in runtime.registry.names()
        finally:
            await runtime.shutdown()

    async def test_features_subagents_false_skips_agent_tools(
        self, tmp_path: Path
    ) -> None:
        cfg = Config()
        cfg.features.subagents = False
        runtime = await create_tool_runtime(
            config=cfg,
            working_directory=tmp_path,
            task_data_dir=tmp_path / "task_data",
        )
        try:
            assert runtime.subagent_manager is None
            assert "agent_spawn" not in runtime.registry.names()
            assert "task_create" in runtime.registry.names()
        finally:
            await runtime.shutdown()

    async def test_runtime_context_manager(
        self, tmp_path: Path, cfg_default: Config
    ) -> None:
        async with await create_tool_runtime(
            config=cfg_default,
            working_directory=tmp_path,
            task_data_dir=tmp_path / "task_data",
            subagent_state_path=tmp_path / "sub.json",
        ) as runtime:
            assert runtime.task_manager is not None
            # Exit runs shutdown
        # Manager stopped — creating a new one on same path must be clean.
        async with await create_tool_runtime(
            config=cfg_default,
            working_directory=tmp_path,
            task_data_dir=tmp_path / "task_data",
            subagent_state_path=tmp_path / "sub.json",
        ) as runtime2:
            assert runtime2.task_manager is not None
