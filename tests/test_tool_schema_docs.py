"""Schema documentation guard: every tool parameter carries a description.

Industry-leaked agent prompts (Claude Code, Cursor, Kimi, OpenCode) document
every tool parameter — description, default, constraints — because the model
can only use what it can read. This test locks that standard in: any NEW tool
(or new parameter) must ship with parameter descriptions.

Tools that predate the standard sit in ``LEGACY_UNDOCUMENTED`` below. That
set may only shrink: when you document a tool's parameters, delete its entry.
Never add entries for new tools.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil

import deepseek_tui.tools as tools_pkg
from deepseek_tui.tools.registry import ToolSpec

# Tools not yet migrated to the fully-documented-schema standard.
# Shrink-only: remove entries as tools are documented; do not add.
# Empty as of the batch-2 migration — keep it that way.
LEGACY_UNDOCUMENTED: dict[str, set[str]] = {}


def _iter_tool_instances():
    for mod_info in pkgutil.walk_packages(
        tools_pkg.__path__, prefix="deepseek_tui.tools."
    ):
        try:
            mod = importlib.import_module(mod_info.name)
        except Exception:  # noqa: BLE001 — optional deps may be absent
            continue
        for _, cls in inspect.getmembers(mod, inspect.isclass):
            if (
                not issubclass(cls, ToolSpec)
                or cls is ToolSpec
                or cls.__module__ != mod_info.name
            ):
                continue
            try:
                inst = cls()
            except Exception:  # noqa: BLE001 — needs runtime wiring; skip
                continue
            try:
                inst.name(), inst.description(), inst.input_schema()
            except Exception:  # noqa: BLE001
                continue
            yield inst


def test_tool_parameters_are_documented():
    undocumented: dict[str, list[str]] = {}
    seen: set[str] = set()
    for inst in _iter_tool_instances():
        tool_name = inst.name()
        seen.add(tool_name)
        schema = inst.input_schema()
        props = schema.get("properties", {}) if isinstance(schema, dict) else {}
        allowed = LEGACY_UNDOCUMENTED.get(tool_name, set())
        missing = [
            param
            for param, spec in props.items()
            if isinstance(spec, dict)
            and not str(spec.get("description", "")).strip()
            and param not in allowed
        ]
        if missing:
            undocumented[tool_name] = missing
    assert seen, "tool discovery found no tools — walker is broken"
    assert not undocumented, (
        "Tool parameters without a description (document them in "
        f"input_schema; do NOT extend LEGACY_UNDOCUMENTED): {undocumented}"
    )


def test_tool_descriptions_not_empty():
    thin = {
        inst.name(): len(inst.description().strip())
        for inst in _iter_tool_instances()
        if len(inst.description().strip()) == 0
    }
    assert not thin, f"Tools with an empty description: {thin}"


def test_legacy_allowlist_shrinks_only():
    """Entries whose parameters are now documented must be removed."""
    stale: list[str] = []
    for inst in _iter_tool_instances():
        tool_name = inst.name()
        if tool_name not in LEGACY_UNDOCUMENTED:
            continue
        schema = inst.input_schema()
        props = schema.get("properties", {}) if isinstance(schema, dict) else {}
        still_missing = {
            param
            for param, spec in props.items()
            if isinstance(spec, dict)
            and not str(spec.get("description", "")).strip()
        }
        if not still_missing & LEGACY_UNDOCUMENTED[tool_name]:
            stale.append(tool_name)
    assert not stale, (
        f"These tools are now documented — remove them from "
        f"LEGACY_UNDOCUMENTED: {stale}"
    )
