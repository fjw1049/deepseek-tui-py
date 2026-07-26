"""Golden snapshot of the default tool catalog.

Guards the Phase 1 tool-surface consolidation (see
docs/TOOL_OPTIMIZATION_PLAN.md): any accidental addition/removal of a
registered tool fails here and must be acknowledged by updating the
golden list deliberately.
"""

from __future__ import annotations

from deepseek_tui.config import Config
from deepseek_tui.tools.registry import _gh_cli_ready, build_default_registry

_AGENT_TOOLS = [
    "agent",
    "agent_resume",
    "checklist",
    "current_time",
    "edit_file",
    "exec_shell",
    "exec_shell_interact",
    "fetch_url",
    "file_search",
    "git",
    "github_close",
    "github_comment",
    "github_issue_context",
    "github_pr_context",
    "grep_files",
    "list_dir",
    "list_mcp_resource_templates",
    "list_mcp_resources",
    "load_skill",
    "mcp_get_prompt",
    "note",
    "project_map",
    "read_file",
    "read_mcp_resource",
    "request_user_input",
    "run_tests",
    "task_cancel",
    "task_create",
    "task_gate_run",
    "task_list",
    "task_read",
    "task_resume",
    "task_shell_start",
    "task_shell_wait",
    "update_plan",
    "web_search",
    "workflow",
    "workflow_list",
    "write_file",
]

_PLAN_TOOLS = [
    "agent",
    "checklist",
    "current_time",
    "fetch_url",
    "file_search",
    "git",
    "github_issue_context",
    "github_pr_context",
    "grep_files",
    "list_dir",
    "list_mcp_resource_templates",
    "list_mcp_resources",
    "load_skill",
    "mcp_get_prompt",
    "project_map",
    "read_file",
    "read_mcp_resource",
    "request_user_input",
    "task_list",
    "task_read",
    "task_shell_wait",
    "update_plan",
    "web_search",
    "workflow_list",
]

_GITHUB_TOOLS = {
    "github_close",
    "github_comment",
    "github_issue_context",
    "github_pr_context",
}


def _expected(names: list[str]) -> list[str]:
    """Golden list adjusted for the gh-dependent github_* tools."""
    if _gh_cli_ready():
        return names
    return [n for n in names if n not in _GITHUB_TOOLS]


def test_agent_mode_catalog_snapshot() -> None:
    names = sorted(build_default_registry(Config(), mode="agent").names())
    assert names == _expected(_AGENT_TOOLS)


def test_plan_mode_catalog_snapshot() -> None:
    names = sorted(build_default_registry(Config(), mode="plan").names())
    assert names == _expected(_PLAN_TOOLS)


def test_plan_mode_has_no_side_effect_tools() -> None:
    """Plan mode must not register mutating/executing tools."""
    side_effect = {
        "write_file",
        "edit_file",
        "exec_shell",
        "exec_shell_interact",
        "github_comment",
        "github_close",
        "task_create",
        "task_cancel",
        "task_resume",
        "task_gate_run",
        "task_shell_start",
        "agent_resume",
        "note",
        "workflow",
        "run_tests",
    }
    names = set(build_default_registry(Config(), mode="plan").names())
    assert not (side_effect & names)


def test_plan_mode_excludes_automations_even_when_enabled() -> None:
    """features.automations must not leak side-effect tools into plan mode."""
    cfg = Config()
    cfg.features.automations = True
    plan_names = set(build_default_registry(cfg, mode="plan").names())
    assert not any(n.startswith("automation_") for n in plan_names)
    agent_names = set(build_default_registry(cfg, mode="agent").names())
    assert "automation_create" in agent_names  # sanity: flag is actually on
