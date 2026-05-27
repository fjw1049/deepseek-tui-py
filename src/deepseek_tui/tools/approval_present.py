"""Build human-readable approval presentation (mirrors ``tui/approval.rs``)."""

from __future__ import annotations

import json
from typing import Any

from deepseek_tui.execpolicy.approval_cache import build_approval_key
from deepseek_tui.execpolicy.command_safety import SafetyLevel, analyze_command
from deepseek_tui.execpolicy.models import ApprovalRequest
from deepseek_tui.engine.dispatch import is_mcp_tool

_PREVIEW_MAX = 4000
_LINE_MAX = 200


def enrich_approval_request(
    request: ApprovalRequest,
    tool_name: str,
    arguments: dict[str, Any] | None,
    *,
    tool_description: str | None = None,
) -> None:
    """Fill presentation fields on ``request`` for UI / SSE."""
    args = arguments if isinstance(arguments, dict) else {}
    cat = classify_tool_category(tool_name)
    risk = classify_presentation_risk(tool_name, cat, args)
    impacts = build_impacts(tool_name, cat, args)
    preview = build_primary_preview(tool_name, cat, args)
    title = localized_title(cat, tool_name)

    if risk == "destructive" and cat == "shell":
        cmd = _param_preview(args, ("command", "cmd"), 96)
        if cmd:
            analysis = analyze_command(cmd)
            if analysis.level == SafetyLevel.DANGEROUS:
                detail = analysis.reasons[0] if analysis.reasons else "dangerous command"
                impacts = [*impacts, f"Warning: {detail}"]

    request.title = title
    request.impacts = impacts
    request.primary_preview = preview
    request.presentation_risk = risk
    request.approval_key = str(build_approval_key(tool_name, args))
    if preview:
        request.input_summary = preview[:500]
    elif tool_description and not request.input_summary:
        request.input_summary = tool_description[:500]
    if tool_description and (
        not request.reason or request.reason.startswith("tool has ")
    ):
        request.reason = tool_description


def approval_request_to_sse_payload(
    approval_id: str, request: ApprovalRequest
) -> dict[str, object]:
    """SSE ``approval.required`` payload with backward-compatible keys."""
    risk_level = (
        "low"
        if request.presentation_risk == "benign"
        else "high" if request.presentation_risk == "destructive"
        else request.risk_level.value
    )
    title = request.title or request.reason
    return {
        "id": approval_id,
        "approval_id": approval_id,
        "tool_name": request.tool_name,
        "title": title,
        "description": title,
        "impacts": list(request.impacts),
        "primary_preview": request.primary_preview or None,
        "input_summary": request.input_summary or request.primary_preview or "",
        "category": classify_tool_category(request.tool_name),
        "risk": request.presentation_risk or None,
        "risk_level": risk_level,
        "approval_key": request.approval_key or None,
    }


def classify_tool_category(tool_name: str) -> str:
    if tool_name in ("write_file", "edit_file", "apply_patch"):
        return "file_write"
    if tool_name in ("web_run", "web_search", "fetch_url"):
        return "network"
    if tool_name in ("exec_shell", "exec_shell_wait", "exec_shell_interact"):
        return "shell"
    if tool_name.startswith("list_mcp_") or tool_name.startswith("read_mcp_"):
        return "mcp_read"
    if tool_name.startswith("mcp_") or is_mcp_tool(tool_name):
        from deepseek_tui.engine.dispatch import mcp_tool_is_read_only

        return "mcp_action" if not mcp_tool_is_read_only(tool_name) else "mcp_read"
    if tool_name.startswith("agent_") or tool_name == "delegate_to_agent":
        return "subagent"
    if tool_name.startswith("task_") or tool_name.startswith("pr_attempt_"):
        return "task"
    if tool_name.startswith("automation_"):
        return "automation"
    if tool_name in (
        "read_file",
        "list_dir",
        "grep_files",
        "file_search",
        "note",
        "update_plan",
    ) or tool_name.startswith(("read_", "list_", "get_")):
        return "safe"
    return "unknown"


def classify_presentation_risk(
    tool_name: str, category: str, args: dict[str, Any]
) -> str:
    if category in ("safe", "mcp_read"):
        return "benign"
    if category == "network":
        return "benign" if tool_name in ("web_search", "web_run") else "destructive"
    if category == "shell":
        cmd = _param_preview(args, ("command", "cmd"), 96)
        if cmd and analyze_command(cmd).level == SafetyLevel.DANGEROUS:
            return "destructive"
        return "destructive"
    if category in (
        "file_write",
        "mcp_action",
        "subagent",
        "task",
        "automation",
        "unknown",
    ):
        return "destructive"
    return "destructive"


def build_impacts(tool_name: str, category: str, args: dict[str, Any]) -> list[str]:
    if category == "safe":
        lines = ["Read-only operation."]
        if path := _param_preview(args, ("path", "ref_id", "uri"), 72):
            lines.append(f"Reads: {path}")
        return lines
    if category == "file_write":
        lines = ["Writes files in the workspace or an approved write scope."]
        if path := _param_preview(args, ("path", "target", "destination"), 72):
            lines.append(f"Writes: {path}")
        if tool_name == "apply_patch" and (args.get("patch") or args.get("changes")):
            lines.append("Applies a unified diff or multi-file patch.")
        return lines
    if category == "shell":
        lines = ["Executes a shell command."]
        if cmd := _param_preview(args, ("command", "cmd"), 96):
            lines.append(f"Command: {cmd}")
        if cwd := _param_preview(args, ("workdir", "cwd"), 72):
            lines.append(f"Working dir: {cwd}")
        return lines
    if category == "network":
        lines = ["May reach network services or remote content."]
        if target := _param_preview(args, ("url", "q", "query"), 96):
            lines.append(f"Target: {target}")
        return lines
    if category == "mcp_read":
        lines = ["Reads from an MCP server without an obvious local write."]
        if server := _mcp_server_hint(tool_name):
            lines.append(f"Server: {server}")
        return lines
    if category == "mcp_action":
        lines = ["Calls an MCP server action that may have side effects."]
        if server := _mcp_server_hint(tool_name):
            lines.append(f"Server: {server}")
        return lines
    if category == "subagent":
        lines = ["Spawns a sub-agent that may run tools in this workspace."]
        if prompt := _param_preview(
            args, ("prompt", "message", "objective"), 120
        ):
            lines.append(f"Task: {prompt}")
        for key, label in (
            ("type", "type"),
            ("model", "model"),
            ("allow_shell", "allow_shell"),
        ):
            if key in args:
                lines.append(f"{label}: {args[key]}")
        return lines
    if category in ("task", "automation"):
        lines = [f"Runs a {category} tool that may change durable state."]
        if prompt := _param_preview(args, ("prompt", "message", "name"), 96):
            lines.append(f"Detail: {prompt}")
        return lines
    lines = ["Tool is not classified. Review parameters before approving."]
    if target := _param_preview(
        args, ("path", "cmd", "command", "url", "q", "query"), 96
    ):
        lines.append(f"Primary input: {target}")
    return lines


def build_primary_preview(
    tool_name: str, category: str, args: dict[str, Any]
) -> str:
    if category == "file_write" and tool_name == "apply_patch":
        patch = args.get("patch")
        if isinstance(patch, str) and patch.strip():
            return _truncate(patch, _PREVIEW_MAX)
        changes = args.get("changes")
        if isinstance(changes, list) and changes:
            paths = []
            for item in changes[:8]:
                if isinstance(item, dict) and isinstance(item.get("path"), str):
                    paths.append(item["path"])
            if paths:
                return "Files:\n" + "\n".join(paths)
    if category == "shell":
        parts = []
        if cmd := _param_preview(args, ("command", "cmd"), _LINE_MAX):
            parts.append(cmd)
        if cwd := _param_preview(args, ("workdir", "cwd"), 72):
            parts.append(f"cwd: {cwd}")
        return "\n".join(parts)
    if category == "network":
        return _param_preview(args, ("url", "q", "query"), _LINE_MAX) or ""
    if category == "subagent":
        return _param_preview(args, ("prompt", "message", "objective"), _PREVIEW_MAX) or ""
    if category == "file_write":
        if content := _param_preview(args, ("content",), 800):
            path = _param_preview(args, ("path",), 72) or "?"
            return f"path: {path}\n\n{content}"
        if search := _param_preview(args, ("search", "replace"), 400):
            path = _param_preview(args, ("path",), 72) or "?"
            return f"path: {path}\nsearch/replace:\n{search}"
    if args:
        try:
            return _truncate(json.dumps(args, ensure_ascii=False, indent=0), 1200)
        except (TypeError, ValueError):
            return _truncate(str(args), 1200)
    return ""


def localized_title(category: str, tool_name: str) -> str:
    titles = {
        "safe": "Read-only operation requested",
        "file_write": "File change requested",
        "shell": "Shell command requested",
        "network": "Network access requested",
        "mcp_read": "MCP read requested",
        "mcp_action": "MCP action requested",
        "subagent": "Sub-agent requested",
        "task": "Task operation requested",
        "automation": "Automation change requested",
        "unknown": f"Approval required for {tool_name}",
    }
    return titles.get(category, f"Approval required for {tool_name}")


def _mcp_server_hint(tool_name: str) -> str | None:
    remainder = tool_name.removeprefix("mcp_")
    if "__" in remainder:
        return remainder.split("__", 1)[0] or None
    if "_" in remainder:
        return remainder.split("_", 1)[0] or None
    return None


def _param_preview(
    args: dict[str, Any], keys: tuple[str, ...], max_len: int
) -> str | None:
    for key in keys:
        if key not in args:
            continue
        value = args[key]
        if value is None:
            continue
        if isinstance(value, str):
            text = value.strip()
            return _truncate(text, max_len) if text else None
        if isinstance(value, (int, float, bool)):
            return str(value)
        if isinstance(value, list) and value:
            preview = ", ".join(
                _truncate(str(item), max_len // 2) for item in value[:3]
            )
            return _truncate(preview, max_len)
    return None


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."
