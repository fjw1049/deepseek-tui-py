"""A write built on a stale read must not silently land.

``write_file`` replaces the whole file, so if the file moved on disk after
the agent read it — a formatter ran, the user edited it, a shell command
rewrote it, a parallel subagent touched it — the write destroys that change
with no error and no trace the model can see. The tool description has
always said "you must have used read_file on it earlier"; nothing enforced
it, and nothing noticed when the read went out of date.

``edit_file`` is deliberately *not* guarded the same way: it only replaces
text it matched, so a stale edit changes what it aimed at rather than
everything else. It gets a better failure message instead.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from deepseek_tui.tools.registry import ToolContext, ToolError, build_default_registry


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def ctx(workspace: Path) -> ToolContext:
    return ToolContext(working_directory=workspace)


def _registry():
    return build_default_registry(mode="agent")


async def _read(ctx: ToolContext, name: str):
    return await _registry().execute("read_file", {"path": name}, ctx)


async def _write(ctx: ToolContext, name: str, content: str):
    return await _registry().execute(
        "write_file", {"path": name, "content": content}, ctx
    )


async def _edit(ctx: ToolContext, name: str, old: str, new: str):
    return await _registry().execute(
        "edit_file", {"path": name, "old_string": old, "new_string": new}, ctx
    )


def _touch_externally(path: Path, content: str) -> None:
    """Stand in for a formatter, the user's editor, or `git checkout`."""
    path.write_text(content, encoding="utf-8")
    # Guarantee a distinguishable stamp even on a coarse-grained clock.
    stat = path.stat()
    import os

    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))


# --- the guard itself ------------------------------------------------------


@pytest.mark.asyncio
async def test_write_after_external_change_is_refused(
    workspace: Path, ctx: ToolContext
) -> None:
    target = workspace / "app.py"
    target.write_text("original\n", encoding="utf-8")
    await _read(ctx, "app.py")

    _touch_externally(target, "someone else's important work\n")

    with pytest.raises(ToolError, match="changed on disk"):
        await _write(ctx, "app.py", "agent's version\n")

    assert target.read_text(encoding="utf-8") == "someone else's important work\n"


@pytest.mark.asyncio
async def test_the_refusal_names_the_one_action_that_clears_it(
    workspace: Path, ctx: ToolContext
) -> None:
    target = workspace / "app.py"
    target.write_text("v1\n", encoding="utf-8")
    await _read(ctx, "app.py")
    _touch_externally(target, "v2\n")

    with pytest.raises(ToolError) as excinfo:
        await _write(ctx, "app.py", "v3\n")
    assert "read_file" in str(excinfo.value)


@pytest.mark.asyncio
async def test_re_reading_clears_the_block(workspace: Path, ctx: ToolContext) -> None:
    target = workspace / "app.py"
    target.write_text("v1\n", encoding="utf-8")
    await _read(ctx, "app.py")
    _touch_externally(target, "v2 from elsewhere\n")

    await _read(ctx, "app.py")
    result = await _write(ctx, "app.py", "v3 informed by v2\n")

    assert result.success
    assert target.read_text(encoding="utf-8") == "v3 informed by v2\n"


# --- what must NOT be blocked ---------------------------------------------


@pytest.mark.asyncio
async def test_a_brand_new_file_writes_freely(
    workspace: Path, ctx: ToolContext
) -> None:
    assert (await _write(ctx, "new.md", "hello\n")).success


@pytest.mark.asyncio
async def test_a_file_this_session_never_read_is_not_blocked(
    workspace: Path, ctx: ToolContext
) -> None:
    """No record is not evidence of a change; guessing would block real work."""
    (workspace / "untouched.md").write_text("pre-existing\n", encoding="utf-8")
    assert (await _write(ctx, "untouched.md", "replaced\n")).success


@pytest.mark.asyncio
async def test_consecutive_writes_by_the_agent_are_fine(
    workspace: Path, ctx: ToolContext
) -> None:
    """The write updates the stamp, so the agent never trips over itself."""
    await _write(ctx, "notes.md", "first\n")
    await _write(ctx, "notes.md", "second\n")
    assert (await _write(ctx, "notes.md", "third\n")).success


@pytest.mark.asyncio
async def test_read_then_write_with_nothing_intervening_is_fine(
    workspace: Path, ctx: ToolContext
) -> None:
    (workspace / "a.txt").write_text("x\n", encoding="utf-8")
    await _read(ctx, "a.txt")
    assert (await _write(ctx, "a.txt", "y\n")).success


@pytest.mark.asyncio
async def test_the_agents_own_edit_does_not_make_a_later_write_stale(
    workspace: Path, ctx: ToolContext
) -> None:
    (workspace / "b.txt").write_text("alpha\n", encoding="utf-8")
    await _read(ctx, "b.txt")
    await _edit(ctx, "b.txt", "alpha", "beta")
    assert (await _write(ctx, "b.txt", "gamma\n")).success


# --- edit_file's asymmetry -------------------------------------------------


@pytest.mark.asyncio
async def test_a_stale_edit_that_still_matches_is_allowed(
    workspace: Path, ctx: ToolContext
) -> None:
    """It replaces what it matched, not everything else — far weaker blast
    radius than a full overwrite, so blocking it would cost more than it saves."""
    target = workspace / "c.py"
    target.write_text("keep me\nTARGET\n", encoding="utf-8")
    await _read(ctx, "c.py")
    _touch_externally(target, "keep me\nTARGET\nappended by someone else\n")

    assert (await _edit(ctx, "c.py", "TARGET", "REPLACED")).success
    text = target.read_text(encoding="utf-8")
    assert "REPLACED" in text
    assert "appended by someone else" in text


@pytest.mark.asyncio
async def test_a_stale_edit_that_misses_blames_the_staleness(
    workspace: Path, ctx: ToolContext
) -> None:
    """"Search string not found" would send the model hunting a typo."""
    target = workspace / "d.py"
    target.write_text("old_line\n", encoding="utf-8")
    await _read(ctx, "d.py")
    _touch_externally(target, "reformatted_line\n")

    with pytest.raises(ToolError, match="changed on disk"):
        await _edit(ctx, "d.py", "old_line", "new_line")


@pytest.mark.asyncio
async def test_a_fresh_edit_that_misses_keeps_the_plain_message(
    workspace: Path, ctx: ToolContext
) -> None:
    (workspace / "e.py").write_text("hello\n", encoding="utf-8")
    await _read(ctx, "e.py")

    with pytest.raises(ToolError, match="Search string not found"):
        await _edit(ctx, "e.py", "nonexistent", "x")


# --- the registry primitive ------------------------------------------------


def test_a_deleted_file_drops_out_of_the_registry(
    workspace: Path, ctx: ToolContext
) -> None:
    target = workspace / "gone.txt"
    target.write_text("here\n", encoding="utf-8")
    ctx.note_file_content(target)
    assert target in ctx.file_reads

    target.unlink()
    ctx.note_file_content(target)
    assert target not in ctx.file_reads
    assert not ctx.changed_since_last_seen(target)


def test_a_same_size_edit_is_still_detected(
    workspace: Path, ctx: ToolContext
) -> None:
    """Size alone would miss it; the mtime is what carries the signal."""
    target = workspace / "same.txt"
    target.write_text("aaaa\n", encoding="utf-8")
    ctx.note_file_content(target)
    _touch_externally(target, "bbbb\n")
    assert ctx.changed_since_last_seen(target)


def test_registries_are_not_shared_between_engines() -> None:
    """``dataclasses.replace`` aliases mutable defaults unless told otherwise.

    Sharing would be actively wrong, not merely untidy: one session's write
    would stamp another session's stale read as current, turning the guard
    off exactly when two agents are working on the same file.
    """
    import dataclasses
    import inspect

    from deepseek_tui.engine.orchestrator.core import Engine

    source = inspect.getsource(Engine.create)
    assert "file_reads={}" in source, "per-engine context must reset the registry"

    base = ToolContext(working_directory=Path("/tmp"))
    aliased = dataclasses.replace(base)
    assert aliased.file_reads is base.file_reads  # the hazard the line above avoids


def test_parallel_reads_do_not_lose_entries(workspace: Path, ctx: ToolContext) -> None:
    """Read-only tools run concurrently; each path is an independent key."""
    names = [f"f{i}.txt" for i in range(20)]
    for name in names:
        (workspace / name).write_text(name, encoding="utf-8")

    async def _run() -> None:
        await asyncio.gather(*(_read(ctx, name) for name in names))

    asyncio.run(_run())
    assert {workspace / n for n in names} <= set(ctx.file_reads)
