"""Focus whitelist must only name real tools (+ documented meta tools)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from deepseek_tui.config import Config
from deepseek_tui.engine.orchestrator.helpers import (
    FOCUS_KERNEL,
    FOCUS_MCP_BASE,
    FOCUS_META_TOOLS,
    FOCUS_PLUGIN_BASE,
    FOCUS_READ_BASE,
    FOCUS_SKILL_BASE,
    FOCUS_WRITE_BASE,
    _FOCUS_KERNEL_REGISTRY,
    _FOCUS_REGISTRY_TOOLS,
)
from deepseek_tui.engine.tools import (
    TOOL_SEARCH_BM25_NAME,
    TOOL_SEARCH_REGEX_NAME,
    _ALWAYS_ACTIVE_TOOLS,
    _SHELL_TOOLS,
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

    names = set(build_default_registry(cfg).names())
    missing = sorted(_FOCUS_REGISTRY_TOOLS - names)
    assert missing == [], f"FOCUS ghosts (not in registry): {missing}"


def test_focus_base_layering() -> None:
    assert FOCUS_META_TOOLS == frozenset({"code_execution"})
    assert FOCUS_KERNEL == _FOCUS_KERNEL_REGISTRY | FOCUS_META_TOOLS
    assert FOCUS_MCP_BASE == FOCUS_KERNEL
    assert FOCUS_SKILL_BASE == FOCUS_KERNEL | frozenset({"load_skill", "checklist"})
    assert FOCUS_PLUGIN_BASE == FOCUS_SKILL_BASE | frozenset({"agent"})
    assert FOCUS_READ_BASE is FOCUS_PLUGIN_BASE or FOCUS_READ_BASE == FOCUS_PLUGIN_BASE
    assert FOCUS_READ_BASE == _FOCUS_REGISTRY_TOOLS | FOCUS_META_TOOLS
    assert FOCUS_WRITE_BASE <= FOCUS_KERNEL

    # MCP ⊂ SKILL ⊂ PLUGIN
    assert FOCUS_MCP_BASE < FOCUS_SKILL_BASE < FOCUS_PLUGIN_BASE

    for base in (FOCUS_MCP_BASE, FOCUS_SKILL_BASE, FOCUS_PLUGIN_BASE):
        assert "note" not in base
        assert "update_plan" not in base
        assert TOOL_SEARCH_BM25_NAME not in base
        assert TOOL_SEARCH_REGEX_NAME not in base
        assert "recall_archive" not in base
        assert "exec_wait" not in base
        assert "exec_interact" not in base


def test_mcp_base_excludes_skill_and_agent_noise() -> None:
    assert "load_skill" not in FOCUS_MCP_BASE
    assert "checklist" not in FOCUS_MCP_BASE
    assert "agent" not in FOCUS_MCP_BASE


def test_current_time_not_registered_without_automations() -> None:
    """current_time was removed (date is injected via the Environment block)."""
    cfg = Config()
    assert cfg.features.automations is False
    names = set(build_default_registry(cfg).names())
    assert "current_time" not in names
    assert "cron_create" not in names


def test_shell_active_sets_have_no_ghost_aliases() -> None:
    assert "exec_wait" not in _ALWAYS_ACTIVE_TOOLS
    assert "exec_interact" not in _ALWAYS_ACTIVE_TOOLS
    assert "exec_wait" not in _SHELL_TOOLS
    assert "exec_interact" not in _SHELL_TOOLS
    assert {"exec_shell"} <= _SHELL_TOOLS


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
            allowed_tools=("workflow", "task_create"),
        )
        # Mirror the /skill branch composition without a full turn.
        allowed = set(FOCUS_SKILL_BASE) | set(skill.allowed_tools or ())
        assert FOCUS_SKILL_BASE <= allowed
        assert {"workflow", "task_create"} <= allowed
        assert "read_file" in allowed
        assert "agent" not in allowed
    finally:
        await engine.shutdown_session()
