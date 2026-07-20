"""Module-level helpers for the engine orchestrator.

Locale/mode/skill detection plus tool-call argument summarization used
for status lines and checklists.
"""

from __future__ import annotations

from typing import Any

from deepseek_tui.engine.prompts import AppMode as _AppMode
from deepseek_tui.protocol.messages import Message, TextBlock

# Scenario / focus default tool surface. Authors rarely declare skill
# ``allowed-tools``, so mounts must ship a usable agent subset by default
# (explore + write + code_execution + shell + agents + web/session helpers).
# Trust still gates plugin-supplied processes (hooks / MCP), not these
# built-ins. Note ``grep_files`` (not ``grep``) — name mismatch historically
# silently excluded grep from every focus mode.
FOCUS_READ_BASE = frozenset(
    {
        # Explore
        "read_file",
        "list_dir",
        "grep_files",
        "file_search",
        "project_map",
        "diagnostics",
        "git_status",
        "git_diff",
        "git_log",
        "git_blame",
        "git_show",
        "github_issue_context",
        "github_pr_context",
        # Session
        "load_skill",
        "note",
        "update_plan",
        "retrieve_tool_result",
        "current_time",
        "checklist_write",
        "checklist_add",
        "checklist_update",
        "checklist_list",
        "request_user_input",
        "recall_archive",
        # Research
        "web_search",
        "fetch_url",
        # Work
        "write_file",
        "edit_file",
        "apply_patch",
        "code_execution",
        # Shell
        "exec_shell",
        "exec_shell_wait",
        "exec_shell_interact",
        "exec_shell_cancel",
        "exec_wait",
        "exec_interact",
        # Agents
        "agent_spawn",
        "agent_result",
        "agent_wait",
        "agent_list",
        "agent_cancel",
        "agent_send_input",
        "agent_assign",
        "close_agent",
        "resume_agent",
        "delegate_to_agent",
    }
)

# Write subset kept for MCP-focus composition and callers that want the
# write trio without the full scenario base.
FOCUS_WRITE_BASE = frozenset({"write_file", "edit_file", "apply_patch"})


def _detect_focus_prefix(text: str, sigil: str) -> str | None:
    """解析整条消息首个 token 为 ``<sigil><name>`` 的情形，返回 ``name``。

    ``sigil`` 为单字符前缀（skill 用 ``/``、MCP 连接器用 ``@``）。未以该
    前缀开头、或前缀后无内容时返回 ``None``。仅看首个 token，与聚焦语义
    一致（`@foo 问题` 命中 `foo`，`看 @foo` 不命中）。
    """
    stripped = (text or "").lstrip()
    if not stripped.startswith(sigil):
        return None
    first = stripped[len(sigil):].split(maxsplit=1)[0] if len(stripped) > len(sigil) else ""
    return first or None


def _strip_focus_prefix(text: str, sigil: str, name: str) -> str:
    """移除整条消息首个 ``<sigil><name>`` token（及一个分隔空白），返回剩余文本。

    与 :func:`_detect_focus_prefix` 对称：仅当首个 token 恰为 ``<sigil><name>``
    时才剥离。用于 MCP 连接器聚焦时把开头的 ``@<name>`` 从用户输入里摘掉，
    避免 :func:`prepare_turn_for_model` 把它当作文件 mention 展开（注入
    ``<missing-file>`` 块或内联同名工作区文件）。剥掉一个空白分隔符后保留
    其余原文，调用方在处理完成后会重新把 ``<sigil><name> `` 拼回用户消息。
    """
    stripped = (text or "").lstrip()
    prefix = f"{sigil}{name}"
    if not stripped.startswith(prefix):
        return text or ""
    rest = stripped[len(prefix):]
    if rest[:1] in (" ", "\t", "\n", "\r"):
        rest = rest[1:]
    return rest


def _detect_focus_skill(text: str, registry: object | None) -> object | None:
    """解析形如 `/data-extract ...` 的前缀，命中已发现 skill 时返回该 Skill。

    仅识别整条消息**首个** token 为 `/<name>` 的情形；`<name>` 用 registry 的
    大小写不敏感查找（``SkillRegistry.get``）。未命中 / 无 registry 返回
    ``None``，调用方即回退到全量逻辑（把 `/xxx` 当普通文本，与现状一致）。
    """
    if registry is None:
        return None
    name = _detect_focus_prefix(text, "/")
    if name is None:
        return None
    return registry.get(name)


def _detect_focus_mcp(text: str, manager: object | None) -> str | None:
    """解析形如 `@github ...` 的前缀，命中已配置的 MCP 连接器时返回其名字。

    与 :func:`_detect_focus_skill` 同构：只看首个 token `@<name>`，在
    ``manager.server_names`` 里大小写不敏感匹配。未命中 / 无 manager 返回
    ``None``，调用方即回退（`@xxx` 当普通文本或文件 mention，与现状一致）。
    """
    if manager is None:
        return None
    name = _detect_focus_prefix(text, "@")
    if name is None:
        return None
    server_names = getattr(manager, "server_names", None) or []
    for server in server_names:
        if server.lower() == name.lower():
            return server
    return None


_PLUGIN_MOUNT_QUALIFIER = "plugin:"


def _detect_plugin_mount(text: str) -> str | None:
    """解析形如 `@plugin:hello-probe ...` 的挂载前缀，返回插件名（或哨兵）。

    与 :func:`_detect_focus_mcp` 共用 `@` sigil，但用 ``plugin:`` 限定符区分：
    首个 token 必须恰为 ``@plugin:<name>`` 才命中，裸 ``@mcp`` 不受影响。
    ``@plugin:off`` / ``@plugin:none`` / ``@plugin:`` 空 一律返回 ``"off"``
    表示摘除。未命中返回 ``None``（调用方回退，把 `@plugin:x` 当普通文本）。
    """
    name = _detect_focus_prefix(text, "@")
    if name is None:
        return None
    lowered = name.lower()
    if not lowered.startswith(_PLUGIN_MOUNT_QUALIFIER):
        return None
    plugin = name[len(_PLUGIN_MOUNT_QUALIFIER):]
    if not plugin or plugin.lower() in ("off", "none"):
        return "off"
    return plugin


def _strip_plugin_mount(text: str, name: str) -> str:
    """移除整条消息首个 ``@plugin:<name>`` token（对称于 detect）。

    ``name`` 为 :func:`_detect_plugin_mount` 返回的插件名或哨兵 ``"off"``。
    复用 :func:`_strip_focus_prefix`，前缀是 ``plugin:<name>``（哨兵时是
    ``plugin:`` 本身，覆盖 ``@plugin:``/``@plugin:off`` 两种写法）。
    """
    if name == "off":
        # 尝试剥 `@plugin:off` / `@plugin:none`，再退到裸 `@plugin:`。
        for token in ("plugin:off", "plugin:none", "plugin:"):
            stripped = _strip_focus_prefix(text, "@", token)
            if stripped != (text or ""):
                return stripped
        return text or ""
    return _strip_focus_prefix(text, "@", f"{_PLUGIN_MOUNT_QUALIFIER}{name}")


def _resolve_app_mode(mode: str) -> _AppMode:
    """Convert a mode string to AppMode, falling back to AGENT."""
    try:
        return _AppMode(mode)
    except ValueError:
        return _AppMode.AGENT


def _clip_summary_line(text: str, limit: int = 200) -> str:
    line = text.strip().splitlines()[0] if text.strip() else ""
    if len(line) > limit:
        return line[: limit - 1] + "…"
    return line


def _format_checklist_entry(entry: object) -> str:
    if isinstance(entry, str) and entry.strip():
        return _clip_summary_line(entry, 80)
    if isinstance(entry, dict):
        content = entry.get("content") or entry.get("text")
        if isinstance(content, str) and content.strip():
            label = _clip_summary_line(content, 80)
            status = entry.get("status")
            if isinstance(status, str) and status.strip():
                return f"{label} [{status.strip()}]"
            return label
    return ""


def _summarize_checklist_args(arguments: dict[str, Any]) -> str:
    """Human-readable approval text for checklist / todo tool calls."""
    item_id = arguments.get("item_id")
    if item_id is not None and str(item_id).strip():
        parts = [f"checklist item #{item_id}"]
        status = arguments.get("status")
        if isinstance(status, str) and status.strip():
            parts.append(f"→ {status.strip()}")
        elif arguments.get("done") is True:
            parts.append("→ completed")
        elif arguments.get("done") is False:
            parts.append("→ pending")
        content = arguments.get("content") or arguments.get("text")
        if isinstance(content, str) and content.strip():
            parts.append(f": {_clip_summary_line(content, 120)}")
        return " ".join(parts)

    for key in ("todos", "items"):
        raw = arguments.get(key)
        if not isinstance(raw, list) or not raw:
            continue
        labels = [_format_checklist_entry(entry) for entry in raw]
        labels = [label for label in labels if label]
        if not labels:
            continue
        preview = "; ".join(labels[:3])
        if len(labels) > 3:
            preview += f"; +{len(labels) - 3} more"
        return f"checklist ({len(labels)} items): {preview}"
    return ""


def _summarize_call_args(arguments: dict[str, Any] | None) -> str:
    """Return a short, single-line summary of a tool's arguments.

    Used to enrich :class:`ApprovalRequest.input_summary` so the TUI
    approval dialog can show *what* is being approved (the actual
    command or path) rather than just the tool name. Picks the first
    non-empty value, takes its first line, and caps the length at 200.

    Prioritizes semantically important keys (prompt, command, path, etc.)
    over arbitrary parameter order to show the most relevant information.
    """
    if not arguments:
        return ""

    checklist_summary = _summarize_checklist_args(arguments)
    if checklist_summary:
        return checklist_summary

    # Priority keys that are most informative for approval decisions
    priority_keys = [
        "prompt", "message", "objective",  # Sub-agent / task descriptions
        "command", "cmd",                   # Shell commands
        "path", "file_path", "source_path", "dest_path",  # File operations
        "content", "text", "input",         # Content being written/sent
    ]

    # First pass: check priority keys
    for key in priority_keys:
        if key in arguments:
            value = arguments[key]
            if value is not None:
                s = str(value).strip()
                if s:
                    return _clip_summary_line(s)

    # Second pass: fallback to any non-empty value (skip checklist ids)
    skip_keys = {"item_id", "done"}
    for key, value in arguments.items():
        if key in skip_keys or value is None:
            continue
        s = str(value).strip()
        if not s:
            continue
        return _clip_summary_line(s)
    return ""


def _assistant_preface_text(message: Message | None) -> str | None:
    if message is None:
        return None
    parts: list[str] = []
    for block in message.content:
        if isinstance(block, TextBlock):
            text = block.text.strip()
            if text:
                parts.append(text)
    joined = "\n".join(parts).strip()
    return joined or None
