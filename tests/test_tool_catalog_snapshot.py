"""Golden snapshot of the default tool catalog.

Guards the Phase 1 tool-surface consolidation (see
docs/TOOL_OPTIMIZATION_PLAN.md): any accidental addition/removal of a
registered tool fails here and must be acknowledged by updating the
golden list deliberately.
"""

from __future__ import annotations

from deepseek_tui.config import Config
from deepseek_tui.tools.registry import build_default_registry

_AGENT_TOOLS = [
    "agent",
    "checklist",
    "edit_file",
    "enter_plan_mode",
    "exec_shell",
    "exit_plan_mode",
    "fetch_url",
    "file_search",
    "grep_files",
    "list_mcp_resources",
    "load_skill",
    "note",
    "read_file",
    "read_mcp_resource",
    "request_user_input",
    "task_create",
    "task_list",
    "task_output",
    "task_stop",
    "update_plan",
    "web_search",
    "write_file",
]

_PLAN_TOOLS = [
    "agent",
    "checklist",
    "exit_plan_mode",
    "fetch_url",
    "file_search",
    "grep_files",
    "list_mcp_resources",
    "load_skill",
    "read_file",
    "read_mcp_resource",
    "request_user_input",
    "task_list",
    "task_output",
    "update_plan",
    "web_search",
]


def test_agent_mode_catalog_snapshot() -> None:
    names = sorted(build_default_registry(Config(), mode="agent").names())
    assert names == _AGENT_TOOLS


def test_plan_mode_catalog_snapshot() -> None:
    names = sorted(build_default_registry(Config(), mode="plan").names())
    assert names == _PLAN_TOOLS


def test_plan_mode_has_no_side_effect_tools() -> None:
    """Plan mode must not register mutating/executing tools."""
    side_effect = {
        "write_file",
        "edit_file",
        "exec_shell",
        "task_create",
        "task_stop",
        "note",
    }
    names = set(build_default_registry(Config(), mode="plan").names())
    assert not (side_effect & names)


def test_plan_mode_agent_tool_hides_resume() -> None:
    """Plan mode must not expose the resume parameter (restarts real work)."""
    registry = build_default_registry(Config(), mode="plan")
    schema = registry.get("agent").input_schema()
    assert "resume" not in schema["properties"]

    agent_registry = build_default_registry(Config(), mode="agent")
    agent_schema = agent_registry.get("agent").input_schema()
    assert "resume" in agent_schema["properties"]


def test_plan_mode_excludes_automations_even_when_enabled() -> None:
    """features.automations must not leak side-effect tools into plan mode."""
    cfg = Config()
    cfg.features.automations = True
    plan_names = set(build_default_registry(cfg, mode="plan").names())
    assert not any(n.startswith("automation_") for n in plan_names)
    assert not any(n.startswith("cron_") for n in plan_names)
    agent_names = set(build_default_registry(cfg, mode="agent").names())
    assert {"cron_create", "cron_list", "cron_delete"} <= agent_names

