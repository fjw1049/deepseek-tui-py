"""Regression guard: the checklist tools expose ONE canonical name family.

These tools used to be registered twice — under canonical ``checklist_*`` names
and legacy ``todo_*`` aliases — so the model's catalog carried two identical
tools sharing one store, which made models flail between them. The aliases were
removed. This guards against re-introducing the duplicate and confirms the
single canonical family still works against the shared in-memory store.
"""

from __future__ import annotations

import pytest

from deepseek_tui.engine.tools import _ALWAYS_ACTIVE_TOOLS
from deepseek_tui.tools.registry import ToolContext, build_default_registry

_LEGACY_NAMES = ["todo_write", "todo_add", "todo_update", "todo_list"]
_CANONICAL_NAMES = [
    "checklist_write",
    "checklist_list",
]


def test_only_canonical_names_registered() -> None:
    """Canonical ``checklist_*`` present; legacy ``todo_*`` aliases gone."""
    names = set(build_default_registry(mode="agent").names())
    for canonical in _CANONICAL_NAMES:
        assert canonical in names, f"canonical {canonical!r} missing"
    for legacy in _LEGACY_NAMES:
        assert legacy not in names, f"legacy alias {legacy!r} should be removed"


def test_no_duplicate_checklist_tools_in_catalog() -> None:
    """No checklist tool name appears more than once in the catalog."""
    names = build_default_registry(mode="agent").names()
    checklist_names = [n for n in names if "checklist" in n or n.startswith("todo_")]
    assert len(checklist_names) == len(set(checklist_names)), checklist_names
    assert set(checklist_names) == set(_CANONICAL_NAMES)


def test_only_canonical_write_is_always_active() -> None:
    """The model sees exactly one always-active checklist write tool."""
    assert "checklist_write" in _ALWAYS_ACTIVE_TOOLS
    assert "todo_write" not in _ALWAYS_ACTIVE_TOOLS


@pytest.mark.asyncio
async def test_canonical_family_shares_one_store(tmp_path) -> None:
    """write / list operate on the same in-memory checklist store."""
    registry = build_default_registry(mode="agent")
    context = ToolContext(working_directory=tmp_path)

    await registry.execute(
        "checklist_write",
        {
            "todos": [
                {"content": "A", "status": "completed"},
                {"content": "B", "status": "in_progress"},
            ]
        },
        context,
    )
    listed = await registry.execute("checklist_list", {}, context)
    assert [it["content"] for it in listed.metadata["items"]] == ["A", "B"]
    assert [it["status"] for it in listed.metadata["items"]] == [
        "completed",
        "in_progress",
    ]
