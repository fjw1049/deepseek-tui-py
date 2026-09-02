"""Focus whitelist must only name real tools (+ documented meta tools)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from deepseek_tui.config import Config
from deepseek_tui.engine.orchestrator.helpers import (
    FOCUS_KERNEL,
    FOCUS_MCP_BASE,
    FOCUS_PLUGIN_BASE,
    FOCUS_SKILL_BASE,
)
from deepseek_tui.tools.registry import build_default_registry


def test_focus_registry_tools_subset_of_default_registry() -> None:
    """Every non-meta focus-base name must exist on the default registry."""
    cfg = Config()
    cfg.features.web_search = True
    cfg.features.shell_tool = True
    cfg.features.mcp = True
    cfg.features.subagents = True
    cfg.allow_shell = True

    registry_tools = FOCUS_PLUGIN_BASE
    names = set(build_default_registry(cfg).names())
    missing = sorted(registry_tools - names)
    assert missing == [], f"FOCUS ghosts (not in registry): {missing}"


def test_focus_base_layering() -> None:
    assert FOCUS_MCP_BASE == FOCUS_KERNEL
    assert FOCUS_KERNEL == frozenset(
        {
            "read_file",
            "grep_files",
            "file_search",
            "write_file",
            "edit_file",
            "exec_shell",
        }
    )
    assert FOCUS_SKILL_BASE == FOCUS_KERNEL | frozenset({"load_skill", "web_search"})
    assert FOCUS_PLUGIN_BASE == FOCUS_SKILL_BASE | frozenset({"agent"})
    assert frozenset({"write_file", "edit_file"}) <= FOCUS_KERNEL

    # MCP ⊂ SKILL ⊂ PLUGIN
    assert FOCUS_MCP_BASE < FOCUS_SKILL_BASE < FOCUS_PLUGIN_BASE

    for base in (FOCUS_MCP_BASE, FOCUS_SKILL_BASE, FOCUS_PLUGIN_BASE):
        assert "note" not in base
        assert "update_plan" not in base
        assert "code_execution" not in base
        assert "recall_archive" not in base
        assert "exec_wait" not in base
        assert "exec_interact" not in base
        assert "fetch_url" not in base
        assert "request_user_input" not in base
        assert "checklist" not in base
    assert "web_search" not in FOCUS_MCP_BASE
    assert "web_search" in FOCUS_SKILL_BASE
    assert "web_search" in FOCUS_PLUGIN_BASE


def test_mcp_base_excludes_skill_and_agent_noise() -> None:
    assert "load_skill" not in FOCUS_MCP_BASE
    assert "checklist" not in FOCUS_MCP_BASE
    assert "agent" not in FOCUS_MCP_BASE
    assert "web_search" not in FOCUS_MCP_BASE
    assert "fetch_url" not in FOCUS_MCP_BASE
    assert "request_user_input" not in FOCUS_MCP_BASE


def test_skill_base_is_kernel_plus_load_skill_and_web_search() -> None:
    assert "load_skill" in FOCUS_SKILL_BASE
    assert "web_search" in FOCUS_SKILL_BASE
    assert "agent" not in FOCUS_SKILL_BASE
    assert FOCUS_SKILL_BASE - FOCUS_KERNEL == frozenset({"load_skill", "web_search"})


def test_current_time_not_registered_without_automations() -> None:
    """current_time was removed (date is injected via the Environment block)."""
    cfg = Config()
    assert cfg.features.automations is False
    names = set(build_default_registry(cfg).names())
    assert "current_time" not in names
    assert "cron_create" not in names


def test_shell_active_sets_have_no_ghost_aliases() -> None:
    assert "exec_wait" not in FOCUS_KERNEL
    assert "exec_interact" not in FOCUS_KERNEL
    assert "exec_shell" in FOCUS_KERNEL


@pytest.mark.asyncio
async def test_mcp_focus_whitelist_uses_mcp_base(tmp_path) -> None:
    from deepseek_tui.engine.handle import EngineHandle
    from deepseek_tui.engine.orchestrator.core import Engine

    workspace = tmp_path / "ws"
    workspace.mkdir()
    engine = await Engine.create(
        EngineHandle(),
        AsyncMock(),
        config=Config(features={"tasks": False, "subagents": False, "mcp": False}),
        working_directory=workspace,
    )
    try:
        engine._server_tool_names = lambda server: {f"mcp_{server}_quote"}  # type: ignore[method-assign]
        tools, servers = engine._mcp_focus_whitelist("yahoo")
        assert servers == frozenset({"yahoo"})
        assert FOCUS_MCP_BASE <= tools
        assert "mcp_yahoo_quote" in tools
        assert "agent" not in tools
        assert "load_skill" not in tools
        assert "checklist" not in tools
        assert "web_search" not in tools
        assert "request_user_input" not in tools
    finally:
        await engine.shutdown_session()


@pytest.mark.asyncio
async def test_skill_focus_allowed_tools_unions_skill_base(tmp_path) -> None:
    from deepseek_tui.engine.handle import EngineHandle
    from deepseek_tui.engine.orchestrator.core import Engine
    from deepseek_tui.integrations.skills import Skill

    workspace = tmp_path / "ws"
    workspace.mkdir()
    engine = await Engine.create(
        EngineHandle(),
        AsyncMock(),
        config=Config(features={"tasks": False, "subagents": False, "mcp": False}),
        working_directory=workspace,
    )
    try:
        skill = Skill(
            name="demo",
            description="d",
            body="body",
            path=workspace / "SKILL.md",
            allowed_tools=("note", "task_create"),
        )
        # Mirror the /skill branch composition without a full turn.
        allowed = set(FOCUS_SKILL_BASE) | set(skill.allowed_tools or ())
        assert FOCUS_SKILL_BASE <= allowed
        assert {"note", "task_create"} <= allowed
        assert "read_file" in allowed
        assert "agent" not in allowed
    finally:
        await engine.shutdown_session()
