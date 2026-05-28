"""Tool visibility profiles — slim catalogs for automation composer and cron runs."""

from __future__ import annotations

from typing import Any

AUTOMATION_COMPOSER_HEADING = "[Scheduled automation request]"
CRON_PROMPT_PREFIX = "[cron:"

TOOL_PROFILE_FULL = "full"
TOOL_PROFILE_AUTOMATION_COMPOSER = "automation_composer"
TOOL_PROFILE_CRON = "cron"

# Composer: schedule creation only — no MCP, no tool_search, no shell.
_AUTOMATION_COMPOSER_NATIVE = frozenset(
    {
        "current_time",
        "automation_create",
        "automation_list",
        "automation_read",
        "automation_update",
        "automation_pause",
        "automation_resume",
        "automation_delete",
        "automation_run",
    }
)

# Cron execution: search/fetch + selected MCP families; no automation_* churn.
_CRON_NATIVE = frozenset(
    {
        "web_search",
        "fetch_url",
        "read_file",
        "grep_files",
    }
)

_CRON_MCP_PREFIXES = (
    "mcp_bing",
    "mcp_china",
    "mcp_yahoo",
    "mcp_fetch",
    "mcp_pozansky",
)


def detect_tool_profile_from_prompt(prompt: str) -> str:
    """Infer profile from wrapped user / cron prompt text."""
    text = prompt.lstrip()
    if text.startswith(AUTOMATION_COMPOSER_HEADING):
        return TOOL_PROFILE_AUTOMATION_COMPOSER
    if text.startswith(CRON_PROMPT_PREFIX):
        return TOOL_PROFILE_CRON
    return TOOL_PROFILE_FULL


def profile_includes_tool_search(profile: str | None) -> bool:
    return profile in (None, TOOL_PROFILE_FULL)


def _tool_name(entry: dict[str, Any]) -> str:
    fn = entry.get("function", entry)
    return str(fn.get("name", ""))


def filter_tools_for_profile(
    tools: list[dict[str, Any]], profile: str | None
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
                clone = _copy_tool_entry(entry)
                fn = clone.get("function", clone)
                fn["defer_loading"] = False
                out.append(clone)
        return out

    if profile == TOOL_PROFILE_CRON:
        out = []
        for entry in tools:
            name = _tool_name(entry)
            if name in _CRON_NATIVE or any(
                name.startswith(prefix) for prefix in _CRON_MCP_PREFIXES
            ):
                clone = _copy_tool_entry(entry)
                fn = clone.get("function", clone)
                fn["defer_loading"] = False
                out.append(clone)
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
