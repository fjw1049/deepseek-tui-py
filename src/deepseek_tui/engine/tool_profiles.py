"""Tool visibility policy, independent of prompt text composition."""

from __future__ import annotations

from typing import Any

# Tool visibility profiles — slim catalogs for automation composer and cron runs.


AUTOMATION_COMPOSER_HEADING = "[Scheduled automation request]"
CRON_PROMPT_PREFIX = "[cron:"

TOOL_PROFILE_FULL = "full"
TOOL_PROFILE_AUTOMATION_COMPOSER = "automation_composer"
TOOL_PROFILE_CRON = "cron"

# Composer: schedule creation only — no MCP, no shell.
_AUTOMATION_COMPOSER_NATIVE = frozenset(
    {
        "cron_create",
        "cron_list",
        "cron_update",
        "cron_delete",
    }
)

# Unattended cron: workspace tools, bounded waits and restricted children.
# External MCP calls require explicit user trust; shell requires an OS sandbox.
# Browser/CUA and interactive questions require a person and stay unavailable.
_CRON_NATIVE = frozenset(
    {
        "web_search",
        "fetch_url",
        "read_file",
        "grep_files",
        "file_search",
        "write_file",
        "edit_file",
        "exec_shell",
        "load_skill",
        "agent",
        "task_output",
    }
)

# Mirror engine.dispatch.is_mcp_tool without importing dispatch (avoids
# prompts ↔ engine cycles). Covers installed server tools + resource helpers.
_CRON_MCP_META = frozenset(
    {
        "list_mcp_resources",
        "list_mcp_resource_templates",
        "mcp_read_resource",
        "read_mcp_resource",
    }
)


def _is_cron_allowed_mcp_tool(name: str, trusted_mcp_tools: tuple[str, ...]) -> bool:
    if name in _CRON_MCP_META:
        return True
    return name in trusted_mcp_tools


def detect_tool_profile_from_prompt(prompt: str) -> str:
    """Legacy compatibility helper; live turns use explicit request metadata."""
    text = prompt.lstrip()
    if text.startswith(AUTOMATION_COMPOSER_HEADING):
        return TOOL_PROFILE_AUTOMATION_COMPOSER
    if text.startswith(CRON_PROMPT_PREFIX):
        return TOOL_PROFILE_CRON
    return TOOL_PROFILE_FULL


def _tool_name(entry: dict[str, Any]) -> str:
    fn = entry.get("function", entry)
    return str(fn.get("name", ""))


def filter_tools_for_profile(
    tools: list[dict[str, Any]], profile: str | None, *, trusted_mcp_tools: tuple[str, ...] = (), allow_browser: bool = False
) -> list[dict[str, Any]]:
    """Return a subset of API tool descriptors for the given profile."""
    if not profile or profile == TOOL_PROFILE_FULL:
        return tools

    if profile == TOOL_PROFILE_AUTOMATION_COMPOSER:
        allowed_native = _AUTOMATION_COMPOSER_NATIVE
        out: list[dict[str, Any]] = []
        for entry in tools:
            name = _tool_name(entry)
            if name in allowed_native:
                out.append(_copy_tool_entry(entry))
        return out

    if profile == TOOL_PROFILE_CRON:
        out = []
        for entry in tools:
            name = _tool_name(entry)
            if cron_tool_allowed(name, trusted_mcp_tools, allow_browser=allow_browser):
                out.append(_copy_tool_entry(entry))
        return out

    return tools


def _copy_tool_entry(entry: dict[str, Any]) -> dict[str, Any]:
    fn = entry.get("function", entry)
    if not isinstance(fn, dict):
        return dict(entry)
    return {
        "type": entry.get("type", "function"),
        "function": dict(fn),
    }




def cron_tool_allowed(name: str, trusted_mcp_tools: tuple[str, ...] = (), *, allow_browser: bool = False) -> bool:
    return (name in _CRON_NATIVE or _is_cron_allowed_mcp_tool(name, trusted_mcp_tools)
            or (name == "browser_use" and allow_browser))
