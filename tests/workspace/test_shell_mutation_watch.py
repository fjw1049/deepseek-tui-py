"""Shell mutation watch — per-command on-disk delta detection."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from deepseek_tui.workspace.shell_mutation_watch import (
    capture_shell_snapshot,
    detect_shell_mutations,
)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    (root / "tracked.py").write_text("v1\n", encoding="utf-8")
    _git(root, "add", "tracked.py")
    _git(root, "commit", "-m", "init")
    return root


@pytest.mark.asyncio
async def test_tracked_file_modified(git_repo: Path) -> None:
    original = "".join(f"line{i}\n" for i in range(1, 11))
    (git_repo / "tracked.py").write_text(original, encoding="utf-8")
    _git(git_repo, "add", "tracked.py")
    _git(git_repo, "commit", "-m", "ten lines")

    snapshot = await capture_shell_snapshot(git_repo)
    assert snapshot.is_git
    # Clean tracked file is not part of the snapshot.
    assert "tracked.py" not in snapshot.contents

    modified = original.replace("line5\n", "line5 changed\n")
    (git_repo / "tracked.py").write_text(modified, encoding="utf-8")

    mutations = await detect_shell_mutations(snapshot)
    assert len(mutations) == 1
    mut = mutations[0]
    assert set(mut) == {
        "path",
        "op",
        "unified_diff",
        "additions",
        "deletions",
        "source",
        "status",
        "line_start",
    }
    assert mut["path"] == "tracked.py"
    assert mut["op"] == "update"
    assert mut["source"] == "shell_detected"
    assert mut["status"] == "applied"
    assert mut["additions"] == 1
    assert mut["deletions"] == 1
    assert "-line5" in mut["unified_diff"]
    assert "+line5 changed" in mut["unified_diff"]
    # First hunk header starts at line 2 (3 context lines before line 5).
    assert mut["line_start"] == 2


@pytest.mark.asyncio
async def test_new_untracked_file_is_create(git_repo: Path) -> None:
    snapshot = await capture_shell_snapshot(git_repo)
    (git_repo / "new.py").write_text("hello\nworld\n", encoding="utf-8")

    mutations = await detect_shell_mutations(snapshot)
    assert len(mutations) == 1
    mut = mutations[0]
    assert mut["path"] == "new.py"
    assert mut["op"] == "create"
    assert mut["line_start"] == 1
    assert mut["additions"] == 2
    assert mut["deletions"] == 0
    assert "--- /dev/null" in mut["unified_diff"]
    assert "+hello" in mut["unified_diff"]


@pytest.mark.asyncio
async def test_deleted_file_is_delete(git_repo: Path) -> None:
    snapshot = await capture_shell_snapshot(git_repo)
    (git_repo / "tracked.py").unlink()

    mutations = await detect_shell_mutations(snapshot)
    assert len(mutations) == 1
    mut = mutations[0]
    assert mut["path"] == "tracked.py"
    assert mut["op"] == "delete"
    assert "line_start" not in mut
    assert mut["deletions"] == 1
    assert mut["additions"] == 0
    assert "+++ /dev/null" in mut["unified_diff"]


@pytest.mark.asyncio
async def test_pre_dirty_file_reports_only_later_change(git_repo: Path) -> None:
    # Dirty BEFORE the snapshot: the snapshot content is the baseline.
    (git_repo / "tracked.py").write_text("dirty\n", encoding="utf-8")
    snapshot = await capture_shell_snapshot(git_repo)
    assert snapshot.contents["tracked.py"] == "dirty\n"

    (git_repo / "tracked.py").write_text("dirty\nmore\n", encoding="utf-8")
    mutations = await detect_shell_mutations(snapshot)
    assert len(mutations) == 1
    mut = mutations[0]
    assert mut["op"] == "update"
    assert mut["additions"] == 1
    assert mut["deletions"] == 0
    assert "+more" in mut["unified_diff"]
    # The pre-existing dirt must not leak into the incremental diff.
    assert "v1" not in mut["unified_diff"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
@pytest.mark.asyncio
async def test_chmod_only_change_is_detected(git_repo: Path) -> None:
    _git(git_repo, "config", "core.filemode", "true")
    target = git_repo / "tracked.py"
    target.chmod(0o644)
    snapshot = await capture_shell_snapshot(git_repo)

    target.chmod(0o755)
    mutations = await detect_shell_mutations(snapshot)

    assert len(mutations) == 1
    assert mutations[0]["path"] == "tracked.py"
    assert mutations[0]["mode_before"] == 0o644
    assert mutations[0]["mode_after"] == 0o755
    assert mutations[0]["additions"] == 0
    assert mutations[0]["deletions"] == 0


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
@pytest.mark.asyncio
async def test_chmod_on_pre_dirty_file_uses_snapshot_mode(git_repo: Path) -> None:
    target = git_repo / "tracked.py"
    target.write_text("dirty\n", encoding="utf-8")
    target.chmod(0o644)
    snapshot = await capture_shell_snapshot(git_repo)
    assert snapshot.modes["tracked.py"] == 0o644

    target.chmod(0o700)
    mutations = await detect_shell_mutations(snapshot)

    assert len(mutations) == 1
    assert mutations[0]["mode_before"] == 0o644
    assert mutations[0]["mode_after"] == 0o700


@pytest.mark.asyncio
async def test_optional_contents_support_turn_net_diff(git_repo: Path) -> None:
    snapshot = await capture_shell_snapshot(git_repo)
    (git_repo / "tracked.py").write_text("v2\n", encoding="utf-8")

    mutations = await detect_shell_mutations(snapshot, include_contents=True)
    assert mutations[0]["_before_content"] == "v1\n"
    assert mutations[0]["_after_content"] == "v2\n"


@pytest.mark.asyncio
async def test_no_change_yields_nothing(git_repo: Path) -> None:
    (git_repo / "tracked.py").write_text("dirty\n", encoding="utf-8")
    snapshot = await capture_shell_snapshot(git_repo)
    assert await detect_shell_mutations(snapshot) == []


@pytest.mark.asyncio
async def test_reverted_to_head_content_is_detected(git_repo: Path) -> None:
    (git_repo / "tracked.py").write_text("dirty\n", encoding="utf-8")
    snapshot = await capture_shell_snapshot(git_repo)
    # Shell command restores the committed content.
    (git_repo / "tracked.py").write_text("v1\n", encoding="utf-8")

    mutations = await detect_shell_mutations(snapshot)
    assert len(mutations) == 1
    mut = mutations[0]
    assert mut["path"] == "tracked.py"
    assert mut["op"] == "update"
    assert "-dirty" in mut["unified_diff"]
    assert "+v1" in mut["unified_diff"]


@pytest.mark.asyncio
async def test_non_git_directory(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "a.py").write_text("x\n", encoding="utf-8")
    snapshot = await capture_shell_snapshot(plain)
    assert not snapshot.is_git
    assert snapshot.contents == {}
    (plain / "a.py").write_text("y\n", encoding="utf-8")
    assert await detect_shell_mutations(snapshot) == []


@pytest.mark.asyncio
async def test_skip_paths_honored(git_repo: Path) -> None:
    snapshot = await capture_shell_snapshot(git_repo)
    (git_repo / "tracked.py").write_text("v2\n", encoding="utf-8")
    (git_repo / "new.py").write_text("n\n", encoding="utf-8")

    mutations = await detect_shell_mutations(snapshot, skip_paths={"tracked.py"})
    assert [m["path"] for m in mutations] == ["new.py"]


@pytest.mark.skipif(os.name == "nt", reason="backslash is a POSIX filename character")
@pytest.mark.asyncio
async def test_skip_paths_preserves_posix_backslash(git_repo: Path) -> None:
    rel = "literal\\name.py"
    (git_repo / rel).write_text("old\n", encoding="utf-8")
    _git(git_repo, "add", rel)
    _git(git_repo, "commit", "-m", "add odd path")
    snapshot = await capture_shell_snapshot(git_repo)
    (git_repo / rel).write_text("changed\n", encoding="utf-8")

    unskipped = await detect_shell_mutations(snapshot)
    assert [mutation["path"] for mutation in unskipped] == [rel]

    mutations = await detect_shell_mutations(snapshot, skip_paths={rel})

    assert mutations == []


@pytest.mark.asyncio
async def test_binary_and_large_files_do_not_choke(git_repo: Path) -> None:
    binary = git_repo / "blob.bin"
    binary.write_bytes(b"\x00\x01\x02" * 64 + bytes(range(256)))
    large = git_repo / "large.txt"
    large.write_text("x" * (600 * 1024), encoding="utf-8")

    snapshot = await capture_shell_snapshot(git_repo)
    # Untracked at snapshot time but unreadable — excluded from contents.
    assert "blob.bin" not in snapshot.contents
    assert "large.txt" not in snapshot.contents

    binary.write_bytes(b"\xff\xfe\x00" * 128)
    large.write_text("y" * (700 * 1024), encoding="utf-8")
    (git_repo / "tracked.py").write_text("v2\n", encoding="utf-8")

    mutations = await detect_shell_mutations(snapshot)
    assert [m["path"] for m in mutations] == ["tracked.py"]
