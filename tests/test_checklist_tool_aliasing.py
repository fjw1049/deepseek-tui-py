"""Regression guard: the checklist tool exposes ONE canonical name.

These tools used to be registered twice — under canonical ``checklist_*``
names and legacy ``todo_*`` aliases — so the model's catalog carried two
identical tools sharing one store, which made models flail between them.
The aliases were removed, and the ``checklist_write`` / ``checklist_list``
pair was later merged into a single ``checklist`` tool (``todos`` present →
write, omitted → read). This guards against re-introducing duplicates and
confirms the merged tool still works against the shared in-memory store,
including the schema-hidden legacy ``items`` argument alias.
"""

from __future__ import annotations

import pytest

from deepseek_tui.engine.tools import _ALWAYS_ACTIVE_TOOLS
from deepseek_tui.tools.registry import ToolContext, build_default_registry

_LEGACY_NAMES = [
    "todo_write",
    "todo_add",
    "todo_update",
    "todo_list",
    "checklist_write",
    "checklist_list",
]
_CANONICAL_NAME = "checklist"


def test_only_canonical_name_registered() -> None:
    """Canonical ``checklist`` present; all legacy names gone."""
    names = set(build_default_registry(mode="agent").names())
    assert _CANONICAL_NAME in names, f"canonical {_CANONICAL_NAME!r} missing"
    for legacy in _LEGACY_NAMES:
        assert legacy not in names, f"legacy name {legacy!r} should be removed"


def test_registered_in_plan_mode_too() -> None:
    """``checklist`` is registered unconditionally, including plan mode."""
    names = set(build_default_registry(mode="plan").names())
    assert _CANONICAL_NAME in names


def test_no_duplicate_checklist_tools_in_catalog() -> None:
    """No checklist tool name appears more than once in the catalog."""
    names = build_default_registry(mode="agent").names()
    checklist_names = [n for n in names if "checklist" in n or n.startswith("todo_")]
    assert len(checklist_names) == len(set(checklist_names)), checklist_names
    assert checklist_names == [_CANONICAL_NAME]


def test_schema_exposes_only_todos_param() -> None:
    """The schema shows only ``todos`` — the legacy ``items`` alias is hidden."""
    registry = build_default_registry(mode="agent")
    assert registry.contains(_CANONICAL_NAME)
    tool = registry.get(_CANONICAL_NAME)
    properties = tool.input_schema().get("properties", {})
    assert set(properties) == {"todos"}


def test_canonical_name_is_always_active() -> None:
    """The model sees exactly one always-active checklist tool."""
    assert _CANONICAL_NAME in _ALWAYS_ACTIVE_TOOLS
    for legacy in _LEGACY_NAMES:
        assert legacy not in _ALWAYS_ACTIVE_TOOLS


@pytest.mark.asyncio
async def test_write_then_read_shares_one_store(tmp_path) -> None:
    """``todos`` present writes; ``todos`` omitted reads the same store."""
    registry = build_default_registry(mode="agent")
    context = ToolContext(working_directory=tmp_path)

    written = await registry.execute(
        _CANONICAL_NAME,
        {
            "todos": [
                {"content": "A", "status": "completed"},
                {"content": "B", "status": "in_progress"},
            ]
        },
        context,
    )
    assert written.success
    # Write path forwards the durable snapshot.
    assert "task_updates" in written.metadata

    listed = await registry.execute(_CANONICAL_NAME, {}, context)
    assert listed.success
    assert [it["content"] for it in listed.metadata["items"]] == ["A", "B"]
    assert [it["status"] for it in listed.metadata["items"]] == [
        "completed",
        "in_progress",
    ]
    # Read path does not forward task_updates.
    assert "task_updates" not in listed.metadata


@pytest.mark.asyncio
async def test_legacy_items_alias_maps_to_todos(tmp_path) -> None:
    """Legacy ``items`` (array of strings) still writes, as pending todos."""
    registry = build_default_registry(mode="agent")
    context = ToolContext(working_directory=tmp_path)

    result = await registry.execute(
        _CANONICAL_NAME, {"items": ["alpha", "beta"]}, context
    )
    assert result.success
    assert [it["content"] for it in result.metadata["items"]] == ["alpha", "beta"]
    assert all(
        it["status"] == "pending" for it in result.metadata["items"]
    )
