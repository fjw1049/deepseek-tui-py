"""Cycle archives must be both named and readable.

Cycling discards the entire pre-cycle history and replaces it with a lossy
briefing. That is only defensible if the discarded detail stays re-fetchable,
which needs two things that used to be missing together: the seed has to name
the archive file, and the read sandbox has to let the model open it.

Naming a file the tools refuse to read would be worse than saying nothing —
the model would spend a turn on a guaranteed error.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deepseek_tui.engine.cycle import CycleBriefing, build_seed_messages
from deepseek_tui.tools.registry import ToolContext

_BRIEFING = CycleBriefing(
    cycle=3,
    timestamp=1_700_000_000,
    briefing_text="Refactored the auth module; tests green.",
    token_estimate=12,
)


def test_seed_names_the_archive_and_says_why() -> None:
    archive = Path("/tmp/ds/sessions/abc/cycles/3.jsonl")
    seeds = build_seed_messages(
        structured_state_block="mode: agent",
        briefing=_BRIEFING,
        pending_user_message="keep going",
        archive_path=archive,
    )

    seeded = "\n".join(s["content"] for s in seeds)
    assert str(archive) in seeded
    # The path alone is inert — the model needs to know when to reach for it.
    assert "lossy" in seeded


def test_seed_omits_the_archive_block_when_there_is_no_path() -> None:
    seeds = build_seed_messages(
        structured_state_block="mode: agent",
        briefing=_BRIEFING,
        pending_user_message="keep going",
    )

    assert "[CYCLE ARCHIVE]" not in "\n".join(s["content"] for s in seeds)


def test_archive_is_unreadable_until_the_root_is_registered(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    cycles = tmp_path / "agent-data" / "sessions" / "s1" / "cycles"
    cycles.mkdir(parents=True)
    archive = cycles / "1.jsonl"
    archive.write_text('{"role":"user"}\n', encoding="utf-8")

    unregistered = ToolContext(working_directory=workspace)
    with pytest.raises(ValueError, match="escapes workspace"):
        unregistered.resolve_path(str(archive), allow_read_roots=True)

    registered = ToolContext(working_directory=workspace, cycle_archive_root=cycles)
    assert registered.resolve_path(str(archive), allow_read_roots=True) == archive


def test_cycle_archive_root_is_read_only(tmp_path: Path) -> None:
    """Write callers pass allow_read_roots=False — the root must not help."""
    workspace = tmp_path / "repo"
    workspace.mkdir()
    cycles = tmp_path / "cycles"
    cycles.mkdir()

    ctx = ToolContext(working_directory=workspace, cycle_archive_root=cycles)
    with pytest.raises(ValueError, match="escapes workspace"):
        ctx.resolve_path(str(cycles / "1.jsonl"))


def test_cycle_archive_root_does_not_widen_to_sibling_sessions(
    tmp_path: Path,
) -> None:
    """Only this session's directory opens, not the whole sessions tree."""
    workspace = tmp_path / "repo"
    workspace.mkdir()
    sessions = tmp_path / "sessions"
    mine = sessions / "s1" / "cycles"
    mine.mkdir(parents=True)
    other = sessions / "s2" / "cycles"
    other.mkdir(parents=True)
    (other / "1.jsonl").write_text("{}\n", encoding="utf-8")

    ctx = ToolContext(working_directory=workspace, cycle_archive_root=mine)
    with pytest.raises(ValueError, match="escapes workspace"):
        ctx.resolve_path(str(other / "1.jsonl"), allow_read_roots=True)
