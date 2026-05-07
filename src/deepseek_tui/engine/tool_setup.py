"""Tool setup and filtering for turn loop.

Mirrors `crates/tui/src/core/engine/tool_setup.rs`
"""

from __future__ import annotations

from typing import Any


def ensure_advanced_tooling(tools: list[dict[str, Any]]) -> None:
    """Ensure system tools are available in the catalog.

    Modifies tools list in-place to add plan/note/etc system tools if missing.
    """
    system_tool_names = {"update_plan", "note"}
    existing_names = {t.get("name") for t in tools}

    for tool_name in system_tool_names:
        if tool_name not in existing_names:
            tools.append(_make_system_tool(tool_name))


def initial_active_tools(tools: list[dict[str, Any]]) -> set[str]:
    """Get initial set of active tool names from catalog."""
    names: set[str] = set()
    for t in tools:
        # Handle both nested function.name and top-level name
        if "name" in t:
            name = t.get("name")
        elif "function" in t:
            name = t.get("function", {}).get("name")
        else:
            continue
        if isinstance(name, str):
            names.add(name)
    return names


def active_tools_for_step(
    tools: list[dict[str, Any]],
    active_names: set[str],
    force_update_plan_first: bool,
) -> list[dict[str, Any]]:
    """Filter tools to only those that should be active for this step.

    Args:
        tools: Full tool catalog
        active_names: Currently active tool names
        force_update_plan_first: If True, only return update_plan tool

    Returns:
        Filtered tool list
    """
    if force_update_plan_first:
        for t in tools:
            tool_name = t.get("name") or t.get("function", {}).get("name")
            if tool_name == "update_plan":
                return [t]
        return []

    filtered = []
    for t in tools:
        tool_name = t.get("name") or t.get("function", {}).get("name")
        if tool_name in active_names:
            filtered.append(t)
    return filtered


def _make_system_tool(name: str) -> dict[str, Any]:
    """Create a system tool definition."""
    descriptions = {
        "update_plan": "Update the current execution plan",
        "note": "Add a note to the working context",
    }
    return {
        "type": "function",
        "name": name,
        "description": descriptions.get(name, f"System tool: {name}"),
        "parameters": {"type": "object"},
    }
