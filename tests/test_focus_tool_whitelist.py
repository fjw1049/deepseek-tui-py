"""Focus whitelist must only name real tools (+ documented meta tools)."""

from __future__ import annotations

from deepseek_tui.config import Config
from deepseek_tui.engine.orchestrator.helpers import (
    FOCUS_META_TOOLS,
    FOCUS_READ_BASE,
    _FOCUS_REGISTRY_TOOLS,
)
from deepseek_tui.engine.tools import _ALWAYS_ACTIVE_TOOLS, _SHELL_TOOLS
from deepseek_tui.tools.registry import build_default_registry


def test_focus_registry_tools_subset_of_default_registry() -> None:
    """Every non-meta FOCUS_READ_BASE name must exist on the default registry."""
    cfg = Config()
    # Enable optional surfaces that FOCUS_READ_BASE names so the subset
    # check is meaningful (web / shell / mcp are feature-gated).
    cfg.features.web_search = True
    cfg.features.shell_tool = True
    cfg.features.mcp = True
    cfg.features.subagents = True
    cfg.allow_shell = True

    names = set(build_default_registry(cfg).names())
    missing = sorted(_FOCUS_REGISTRY_TOOLS - names)
    assert missing == [], f"FOCUS ghosts (not in registry): {missing}"


def test_focus_read_base_is_registry_plus_meta() -> None:
    assert FOCUS_READ_BASE == _FOCUS_REGISTRY_TOOLS | FOCUS_META_TOOLS
    assert FOCUS_META_TOOLS == frozenset({"code_execution"})
    assert "recall_archive" not in FOCUS_READ_BASE
    assert "exec_wait" not in FOCUS_READ_BASE
    assert "exec_interact" not in FOCUS_READ_BASE


def test_current_time_registered_without_automations() -> None:
    cfg = Config()
    assert cfg.features.automations is False
    names = set(build_default_registry(cfg).names())
    assert "current_time" in names
    assert "automation_create" not in names


def test_shell_active_sets_have_no_ghost_aliases() -> None:
    assert "exec_wait" not in _ALWAYS_ACTIVE_TOOLS
    assert "exec_interact" not in _ALWAYS_ACTIVE_TOOLS
    assert "exec_wait" not in _SHELL_TOOLS
    assert "exec_interact" not in _SHELL_TOOLS
    assert {"exec_shell", "exec_shell_interact"} <= _SHELL_TOOLS
