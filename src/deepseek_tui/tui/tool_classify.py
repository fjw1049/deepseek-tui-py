"""Tool display classification — inline vs block rendering mode.

Each tool is classified into one of two visual modes:

- **inline**: Single-line compact display (grep, read, ls, etc.)
- **block**: Panel with left border + expandable content (edit, shell output, etc.)

The classification drives which widget class ``Transcript`` mounts for a
given ``ToolCallEvent``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class ToolDisplay:
    """How a tool call should be rendered in the transcript."""

    mode: Literal["inline", "block"]
    icon: str
    verb: str


# ── Classification tables ────────────────────────────────────────────

_INLINE_TOOLS: dict[str, tuple[str, str]] = {
    # Read / search
    "read_file": ("→", "read"),
    "grep_files": ("✱", "grep"),
    "file_search": ("✱", "search"),
    "list_dir": ("☰", "ls"),
    "project_map": ("☰", "map"),
    # Web
    "web_search": ("◈", "web"),
    "fetch_url": ("⇣", "fetch"),
    # Git (read-only)
    "git_status": ("◈", "status"),
    "git_diff": ("◈", "diff"),
    "git_log": ("◈", "log"),
    "git_show": ("◈", "show"),
    "git_blame": ("◈", "blame"),
    # GitHub (read-only)
    "github_issue_context": ("◈", "issue"),
    "github_pr_context": ("◈", "pr"),
    # Knowledge
    "note": ("◇", "note"),
    # Plan / checklist
    "update_plan": ("◇", "plan"),
    "checklist_write": ("◇", "checklist"),
    "checklist_add": ("◇", "checklist"),
    "checklist_update": ("◇", "checklist"),
    "checklist_list": ("◇", "checklist"),
    "todo_write": ("◇", "todo"),
    "todo_add": ("◇", "todo"),
    "todo_update": ("◇", "todo"),
    "todo_list": ("◇", "todo"),
    # Task management
    "task_create": ("◇", "task"),
    "task_list": ("◇", "task"),
    "task_read": ("◇", "task"),
    "task_cancel": ("◇", "task"),
    "task_gate_run": ("◇", "task"),
    "task_shell_start": ("◇", "task"),
    "task_shell_wait": ("◇", "task"),
    # Agent
    "agent_spawn": ("◐", "spawn"),
    "agent_result": ("◐", "result"),
    "agent_wait": ("◐", "wait"),
    "agent_list": ("◐", "agents"),
    "agent_cancel": ("◐", "cancel"),
    "agent_send_input": ("◐", "input"),
    "agent_assign": ("◐", "assign"),
    "close_agent": ("◐", "close"),
    "resume_agent": ("◐", "resume"),
    "delegate_to_agent": ("◐", "delegate"),
    # MCP
    "list_mcp_resources": ("◇", "mcp"),
    "list_mcp_resource_templates": ("◇", "mcp"),
    "read_mcp_resource": ("◇", "mcp"),
    "mcp_get_prompt": ("◇", "mcp"),
    # Validation / misc
    "validate_data": ("◇", "validate"),
    "run_tests": ("◇", "test"),
    "diagnostics": ("◇", "diag"),
    "current_time": ("◇", "time"),
    "request_user_input": ("◇", "input"),
    "retrieve_tool_result": ("◇", "retrieve"),
    "load_skill": ("◇", "skill"),
    # PR attempt
    "pr_attempt_record": ("◇", "pr"),
    "pr_attempt_list": ("◇", "pr"),
    "pr_attempt_read": ("◇", "pr"),
    "pr_attempt_preflight": ("◇", "pr"),
    # Automation (read)
    "automation_list": ("◇", "auto"),
    "automation_read": ("◇", "auto"),
    # Shell cancel / stop (no output expected)
    "exec_shell_cancel": ("⊘", "stop"),
}

_BLOCK_TOOLS: dict[str, tuple[str, str]] = {
    # File writes
    "write_file": ("←", "write"),
    "edit_file": ("←", "edit"),
    "apply_patch": ("←", "patch"),
    "multi_edit": ("←", "patch"),
    # Shell with output
    "exec_shell": ("$", "run"),
    "exec_shell_wait": ("$", "run"),
    "exec_shell_interact": ("$", "run"),
    # GitHub writes
    "github_comment": ("◈", "comment"),
    "github_close": ("◈", "close"),
    # Workflow
    "workflow": ("▶", "workflow"),
    # Revert
    "revert_turn": ("⊘", "revert"),
    # Structured output
    "structured_output": ("◇", "output"),
    # Automation (write)
    "automation_create": ("◇", "auto"),
    "automation_update": ("◇", "auto"),
    "automation_pause": ("◇", "auto"),
    "automation_resume": ("◇", "auto"),
    "automation_delete": ("◇", "auto"),
    "automation_run": ("◇", "auto"),
}


def classify_tool(name: str, *, has_output: bool = False) -> ToolDisplay:
    """Classify a tool call for display routing.

    Parameters
    ----------
    name:
        The tool name string from ``ToolCall.name``.
    has_output:
        For ``exec_shell``, whether the result contains non-empty output.
        When False and the tool is ``exec_shell``, it renders as inline.
    """
    # Explicit inline match
    if name in _INLINE_TOOLS:
        icon, verb = _INLINE_TOOLS[name]
        return ToolDisplay(mode="inline", icon=icon, verb=verb)

    # Explicit block match
    if name in _BLOCK_TOOLS:
        # exec_shell with no output → inline
        if name == "exec_shell" and not has_output:
            return ToolDisplay(mode="inline", icon="$", verb="run")
        icon, verb = _BLOCK_TOOLS[name]
        return ToolDisplay(mode="block", icon=icon, verb=verb)

    # Prefix heuristics for unknown tools
    if name.startswith("git_"):
        return ToolDisplay(mode="inline", icon="◈", verb="git")
    if name.startswith("github_"):
        return ToolDisplay(mode="inline", icon="◈", verb="github")
    if name.startswith("agent_"):
        return ToolDisplay(mode="inline", icon="◐", verb="agent")
    if name.startswith("task_"):
        return ToolDisplay(mode="inline", icon="◇", verb="task")
    if name.startswith("mcp_") or name.startswith("list_mcp"):
        return ToolDisplay(mode="inline", icon="◇", verb="mcp")
    if name.startswith("automation_"):
        return ToolDisplay(mode="inline", icon="◇", verb="auto")

    # Default: inline with generic icon
    return ToolDisplay(mode="inline", icon="◇", verb=name)
