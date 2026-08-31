"""Per-turn file checkpoints — record / restore semantics."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

import deepseek_tui.workspace.managed_worktree as managed_worktree
import deepseek_tui.workspace.turn_checkpoints as checkpoint_module
from deepseek_tui.workspace.shell_mutation_watch import ShellMutationSnapshot
from deepseek_tui.workspace.turn_checkpoints import (
    RawCheckpointError,
    TurnCheckpoint,
    TurnCheckpointStore,
)


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


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


@pytest.fixture
def store(tmp_path: Path) -> TurnCheckpointStore:
    return TurnCheckpointStore(tmp_path / "checkpoints")


def test_begin_turn_seeds_pre_contents_from_snapshot(store: TurnCheckpointStore) -> None:
    snapshot = ShellMutationSnapshot(
        workspace=Path("/ws"), is_git=True, contents={"dirty.py": "old\n"}
    )
    cp = store.begin_turn("turn_1", snapshot, head="abc", is_git=True)
    assert cp.pre_contents == {"dirty.py": "old\n"}
    assert cp.mutated == []
    # Persisted to disk.
    loaded = store.load("turn_1")
    assert loaded is not None
    assert loaded.head == "abc"
    assert loaded.is_git


def test_record_pre_write_first_touch_wins(store: TurnCheckpointStore) -> None:
    store.begin_turn("turn_1", None, head=None, is_git=False)
    store.record_pre_write("turn_1", "a.py", "original")
    store.record_pre_write("turn_1", "a.py", "later")
    cp = store.load("turn_1")
    assert cp is not None
    assert cp.pre_contents["a.py"] == "original"
    assert cp.mutated == ["a.py"]


def test_write_pre_image_without_fchmod(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    monkeypatch.delattr(os, "fchmod", raising=False)

    checkpoint_module._write_pre_image(root, "script.py", "restored\n", 0o750)

    target = root / "script.py"
    assert target.read_text(encoding="utf-8") == "restored\n"
    assert target.stat().st_mode & 0o777 == 0o750


@pytest.mark.skipif(os.name == "nt", reason="backslash is a POSIX filename character")
@pytest.mark.asyncio
async def test_checkpoint_preserves_odd_posix_filename(
    store: TurnCheckpointStore, tmp_path: Path
) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    rel = " odd\\name.py "
    target = ws / rel
    target.write_text("old\n", encoding="utf-8")
    store.begin_turn(
        "turn_odd", None, head=None, is_git=False, execution_root=str(ws)
    )
    store.record_pre_write("turn_odd", rel, "old\n")
    target.write_text("new\n", encoding="utf-8")
    store.record_post_images("turn_odd", ws)

    report = await store.restore(["turn_odd"], ws)

    checkpoint = store.load("turn_odd")
    assert checkpoint is not None
    assert checkpoint.mutated == [rel]
    assert checkpoint.post_signatures_captured is True
    assert list(checkpoint.post_signatures) == [rel]
    assert report.restored == [rel]
    assert target.read_text(encoding="utf-8") == "old\n"


def test_record_out_of_band_appends_mutated_only(store: TurnCheckpointStore) -> None:
    store.begin_turn("turn_1", None, head=None, is_git=False)
    store.record_out_of_band("turn_1", "shell.py")
    store.record_out_of_band("turn_1", "shell.py")
    cp = store.load("turn_1")
    assert cp is not None
    assert cp.mutated == ["shell.py"]
    assert cp.pre_contents == {}


def test_record_on_missing_turn_is_noop(store: TurnCheckpointStore) -> None:
    store.record_pre_write("turn_nope", "a.py", "x")
    store.record_out_of_band("turn_nope", "a.py")
    assert store.load("turn_nope") is None


@pytest.mark.asyncio
async def test_restore_newest_to_oldest_order(store: TurnCheckpointStore, tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    # turn_1 wrote over "v1" -> "v2"; turn_2 wrote over "v2" -> "v3".
    store.begin_turn("turn_1", None, head=None, is_git=False)
    store.record_pre_write("turn_1", "f.py", "v1\n")
    (ws / "f.py").write_text("v2\n", encoding="utf-8")
    store.record_post_images("turn_1", ws)
    store.begin_turn("turn_2", None, head=None, is_git=False)
    store.record_pre_write("turn_2", "f.py", "v2\n")
    (ws / "f.py").write_text("v3\n", encoding="utf-8")
    store.record_post_images("turn_2", ws)

    report = await store.restore(["turn_2", "turn_1"], ws)

    assert (ws / "f.py").read_text(encoding="utf-8") == "v1\n"
    assert report.restored == ["f.py"]
    assert report.skipped == []
    assert report.turns_without_checkpoint == []


@pytest.mark.asyncio
async def test_restore_none_pre_content_deletes_file(
    store: TurnCheckpointStore, tmp_path: Path
) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    store.begin_turn("turn_1", None, head=None, is_git=False)
    store.record_pre_write("turn_1", "new.py", None)  # created by the turn
    (ws / "new.py").write_text("created\n", encoding="utf-8")
    store.record_post_images("turn_1", ws)

    report = await store.restore(["turn_1"], ws)

    assert not (ws / "new.py").exists()
    assert report.restored == ["new.py"]


@pytest.mark.asyncio
async def test_restore_git_show_fallback_for_clean_tracked_file(
    store: TurnCheckpointStore, git_repo: Path
) -> None:
    head = _git(git_repo, "rev-parse", "HEAD")
    store.begin_turn("turn_1", None, head=head, is_git=True)
    store.record_out_of_band("turn_1", "tracked.py")
    (git_repo / "tracked.py").write_text("changed\n", encoding="utf-8")
    store.record_post_images("turn_1", git_repo)

    report = await store.restore(["turn_1"], git_repo)

    assert (git_repo / "tracked.py").read_text(encoding="utf-8") == "v1\n"
    assert report.restored == ["tracked.py"]


@pytest.mark.asyncio
async def test_restore_git_tree_proves_file_did_not_exist(
    store: TurnCheckpointStore, git_repo: Path
) -> None:
    head = _git(git_repo, "rev-parse", "HEAD")
    store.begin_turn("turn_1", None, head=head, is_git=True)
    store.record_out_of_band("turn_1", "created_by_shell.py")
    (git_repo / "created_by_shell.py").write_text("new\n", encoding="utf-8")
    store.record_post_images("turn_1", git_repo)

    report = await store.restore(["turn_1"], git_repo)

    assert not (git_repo / "created_by_shell.py").exists()
    assert report.restored == ["created_by_shell.py"]


@pytest.mark.asyncio
async def test_restore_git_failure_never_means_file_absent(
    store: TurnCheckpointStore,
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    head = _git(git_repo, "rev-parse", "HEAD")
    store.begin_turn("turn_1", None, head=head, is_git=True)
    store.record_out_of_band("turn_1", "tracked.py")
    (git_repo / "tracked.py").write_text("changed\n", encoding="utf-8")
    store.record_post_images("turn_1", git_repo)

    def fail_git(*args, **kwargs):
        del args, kwargs
        return subprocess.CompletedProcess(["git"], 128, b"", b"temporary failure")

    monkeypatch.setattr(checkpoint_module.subprocess, "run", fail_git)

    report = await store.restore(["turn_1"], git_repo)

    assert report.restored == []
    assert report.skipped == ["tracked.py"]
    assert (git_repo / "tracked.py").read_text(encoding="utf-8") == "changed\n"


@pytest.mark.asyncio
async def test_restore_out_of_band_without_post_image_conflicts(
    store: TurnCheckpointStore, git_repo: Path
) -> None:
    """No post-image means ownership cannot be proven — never delete/revert."""
    head = _git(git_repo, "rev-parse", "HEAD")
    store.begin_turn("turn_1", None, head=head, is_git=True)
    store.record_out_of_band("turn_1", "created_by_shell.py")
    (git_repo / "created_by_shell.py").write_text("new\n", encoding="utf-8")

    report = await store.restore(["turn_1"], git_repo)

    assert report.restored == []
    assert report.conflicted == ["created_by_shell.py"]
    assert (git_repo / "created_by_shell.py").read_text(encoding="utf-8") == "new\n"


@pytest.mark.asyncio
async def test_restore_merges_around_third_party_edit(
    store: TurnCheckpointStore, tmp_path: Path
) -> None:
    """Edits made after the turn in a different region are kept."""
    ws = tmp_path / "ws"
    ws.mkdir()
    pre = "one\ntwo\nthree\nfour\nfive\nsix\nseven\neight\nnine\nten\n"
    post = pre.replace("two\n", "TURN\n")
    third_party = post.replace("nine\n", "OTHER\n")
    store.begin_turn("turn_1", None, head=None, is_git=False)
    store.record_pre_write("turn_1", "f.py", pre)
    (ws / "f.py").write_text(post, encoding="utf-8")
    store.record_post_images("turn_1", ws)
    (ws / "f.py").write_text(third_party, encoding="utf-8")

    report = await store.restore(["turn_1"], ws)

    # The turn's change (two -> TURN) is reverted, the third-party change
    # (nine -> OTHER) survives.
    assert (ws / "f.py").read_text(encoding="utf-8") == pre.replace(
        "nine\n", "OTHER\n"
    )
    assert report.merged == ["f.py"]
    assert report.restored == []
    assert report.conflicted == []


@pytest.mark.asyncio
async def test_restore_conflicting_third_party_edit_left_untouched(
    store: TurnCheckpointStore, tmp_path: Path
) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    store.begin_turn("turn_1", None, head=None, is_git=False)
    store.record_pre_write("turn_1", "f.py", "old\n")
    (ws / "f.py").write_text("turn\n", encoding="utf-8")
    store.record_post_images("turn_1", ws)
    # Same line rewritten by someone else after the turn.
    (ws / "f.py").write_text("someone else\n", encoding="utf-8")

    report = await store.restore(["turn_1"], ws)

    assert report.conflicted == ["f.py"]
    assert report.restored == []
    assert (ws / "f.py").read_text(encoding="utf-8") == "someone else\n"


@pytest.mark.asyncio
async def test_restore_force_overwrites_conflicts(
    store: TurnCheckpointStore, tmp_path: Path
) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    store.begin_turn("turn_1", None, head=None, is_git=False)
    store.record_pre_write("turn_1", "f.py", "old\n")
    (ws / "f.py").write_text("turn\n", encoding="utf-8")
    store.record_post_images("turn_1", ws)
    (ws / "f.py").write_text("someone else\n", encoding="utf-8")

    report = await store.restore(["turn_1"], ws, force=True)

    assert report.restored == ["f.py"]
    assert report.conflicted == []
    assert (ws / "f.py").read_text(encoding="utf-8") == "old\n"


@pytest.mark.asyncio
async def test_restore_uncertain_path_never_merges(
    store: TurnCheckpointStore, git_repo: Path
) -> None:
    """Reconcile-attributed paths need an exact post match; a divergence is a
    conflict even when a three-way merge would succeed."""
    pre = "one\ntwo\nthree\nfour\nfive\nsix\nseven\neight\nnine\nten\n"
    (git_repo / "tracked.py").write_text(pre, encoding="utf-8")
    _git(git_repo, "add", "tracked.py")
    _git(git_repo, "commit", "-m", "long file")
    head = _git(git_repo, "rev-parse", "HEAD")
    store.begin_turn("turn_1", None, head=head, is_git=True)
    store.record_out_of_band("turn_1", "tracked.py", uncertain=True)
    (git_repo / "tracked.py").write_text(
        pre.replace("two\n", "TURN\n"), encoding="utf-8"
    )
    store.record_post_images("turn_1", git_repo)
    (git_repo / "tracked.py").write_text(
        pre.replace("two\n", "TURN\n").replace("nine\n", "OTHER\n"),
        encoding="utf-8",
    )

    report = await store.restore(["turn_1"], git_repo)

    assert report.conflicted == ["tracked.py"]
    assert report.merged == []


@pytest.mark.asyncio
async def test_restore_already_at_pre_state_is_noop(
    store: TurnCheckpointStore, tmp_path: Path
) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    store.begin_turn("turn_1", None, head=None, is_git=False)
    store.record_pre_write("turn_1", "f.py", "old\n")
    (ws / "f.py").write_text("turn\n", encoding="utf-8")
    store.record_post_images("turn_1", ws)
    # Someone already reverted the file (e.g. git checkout).
    (ws / "f.py").write_text("old\n", encoding="utf-8")

    report = await store.restore(["turn_1"], ws)

    assert report.restored == ["f.py"]
    assert report.conflicted == []
    assert (ws / "f.py").read_text(encoding="utf-8") == "old\n"


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
@pytest.mark.asyncio
async def test_restore_reverts_chmod_only_change(
    store: TurnCheckpointStore, tmp_path: Path
) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    target = ws / "run.sh"
    target.write_text("echo ok\n", encoding="utf-8")
    target.chmod(0o644)
    store.begin_turn(
        "turn_1", None, head=None, is_git=False, execution_root=str(ws)
    )
    store.record_pre_write("turn_1", "run.sh", "echo ok\n")
    target.chmod(0o755)
    store.record_post_images("turn_1", ws)

    report = await store.restore(["turn_1"], ws)

    assert report.restored == ["run.sh"]
    assert report.conflicted == []
    assert target.stat().st_mode & 0o777 == 0o644


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
@pytest.mark.asyncio
async def test_restore_does_not_overwrite_third_party_mode_change(
    store: TurnCheckpointStore, tmp_path: Path
) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    target = ws / "run.sh"
    target.write_text("echo ok\n", encoding="utf-8")
    target.chmod(0o644)
    store.begin_turn(
        "turn_1", None, head=None, is_git=False, execution_root=str(ws)
    )
    store.record_pre_write("turn_1", "run.sh", "echo ok\n")
    target.chmod(0o755)
    store.record_post_images("turn_1", ws)
    target.chmod(0o700)

    report = await store.restore(["turn_1"], ws)

    assert report.restored == []
    assert report.conflicted == ["run.sh"]
    assert target.stat().st_mode & 0o777 == 0o700


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
@pytest.mark.asyncio
async def test_restore_keeps_unowned_mode_while_reverting_content(
    store: TurnCheckpointStore, tmp_path: Path
) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    target = ws / "run.sh"
    target.write_text("before\n", encoding="utf-8")
    target.chmod(0o644)
    store.begin_turn(
        "turn_1", None, head=None, is_git=False, execution_root=str(ws)
    )
    store.record_pre_write("turn_1", "run.sh", "before\n")
    target.write_text("after\n", encoding="utf-8")
    store.record_post_images("turn_1", ws)
    target.chmod(0o700)

    report = await store.restore(["turn_1"], ws)

    assert report.restored == ["run.sh"]
    assert report.conflicted == []
    assert target.read_text(encoding="utf-8") == "before\n"
    assert target.stat().st_mode & 0o777 == 0o700


@pytest.mark.asyncio
async def test_preview_reports_statuses_without_touching_disk(
    store: TurnCheckpointStore, tmp_path: Path
) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    store.begin_turn("turn_1", None, head=None, is_git=False)
    store.record_pre_write("turn_1", "safe.py", "old\n")
    store.record_pre_write("turn_1", "conflict.py", "old\n")
    (ws / "safe.py").write_text("turn\n", encoding="utf-8")
    (ws / "conflict.py").write_text("turn\n", encoding="utf-8")
    store.record_post_images("turn_1", ws)
    (ws / "conflict.py").write_text("someone else\n", encoding="utf-8")

    statuses = await store.preview(["turn_1"], ws)

    assert statuses == {"safe.py": "restored", "conflict.py": "conflicted"}
    # Disk untouched by the dry run.
    assert (ws / "safe.py").read_text(encoding="utf-8") == "turn\n"
    assert (ws / "conflict.py").read_text(encoding="utf-8") == "someone else\n"


@pytest.mark.asyncio
async def test_restore_non_git_out_of_band_is_skipped(
    store: TurnCheckpointStore, tmp_path: Path
) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    store.begin_turn("turn_1", None, head=None, is_git=False)
    store.record_out_of_band("turn_1", "opaque.py")
    (ws / "opaque.py").write_text("changed\n", encoding="utf-8")

    report = await store.restore(["turn_1"], ws)

    assert report.restored == []
    assert report.skipped == ["opaque.py"]
    # File left untouched.
    assert (ws / "opaque.py").read_text(encoding="utf-8") == "changed\n"


@pytest.mark.asyncio
async def test_restore_missing_checkpoint_recorded(
    store: TurnCheckpointStore, tmp_path: Path
) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    store.begin_turn("turn_1", None, head=None, is_git=False)
    store.record_pre_write("turn_1", "a.py", "old\n")
    (ws / "a.py").write_text("new\n", encoding="utf-8")
    store.record_post_images("turn_1", ws)

    report = await store.restore(["turn_2", "turn_1"], ws)

    assert report.turns_without_checkpoint == ["turn_2"]
    assert (ws / "a.py").read_text(encoding="utf-8") == "old\n"


@pytest.mark.asyncio
async def test_restore_path_skipped_in_newer_turn_resolved_by_older(
    store: TurnCheckpointStore, tmp_path: Path
) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    # Newer turn cannot resolve the pre-image; older one can.
    store.begin_turn("turn_1", None, head=None, is_git=False)
    store.record_pre_write("turn_1", "f.py", "v1\n")
    (ws / "f.py").write_text("v2\n", encoding="utf-8")
    store.record_post_images("turn_1", ws)
    store.begin_turn("turn_2", None, head=None, is_git=False)
    store.record_out_of_band("turn_2", "f.py")

    report = await store.restore(["turn_2", "turn_1"], ws)

    assert (ws / "f.py").read_text(encoding="utf-8") == "v1\n"
    assert report.restored == ["f.py"]
    assert report.skipped == []


def test_delete_removes_checkpoint(store: TurnCheckpointStore) -> None:
    store.begin_turn("turn_1", None, head=None, is_git=False)
    sidecars = store._raw_sidecar_dir("turn_1")
    sidecars.mkdir()
    (sidecars / "payload.pre").write_bytes(b"durable")
    store.delete("turn_1")
    assert store.load("turn_1") is None
    assert not sidecars.exists()
    # Idempotent.
    store.delete("turn_1")


@pytest.mark.asyncio
async def test_restore_binary_blob_at_head_is_skipped_not_deleted(
    store: TurnCheckpointStore, git_repo: Path
) -> None:
    blob = b"\x89PNG\r\n\x1a\n\xff\xfe binary \x00\x01"
    (git_repo / "logo.bin").write_bytes(blob)
    _git(git_repo, "add", "logo.bin")
    _git(git_repo, "commit", "-m", "add binary")
    head = _git(git_repo, "rev-parse", "HEAD")
    store.begin_turn("turn_1", None, head=head, is_git=True)
    store.record_out_of_band("turn_1", "logo.bin")
    changed = b"\x00\xff changed by the turn \x89"
    (git_repo / "logo.bin").write_bytes(changed)

    report = await store.restore(["turn_1"], git_repo)

    # Undecodable at HEAD: skipped, and the on-disk file is never unlinked.
    assert report.restored == []
    assert report.skipped == ["logo.bin"]
    assert (git_repo / "logo.bin").read_bytes() == changed


def test_begin_turn_records_thread_id_and_created_at(store: TurnCheckpointStore) -> None:
    cp = store.begin_turn("turn_1", None, head=None, is_git=False, thread_id="t1")
    assert cp.thread_id == "t1"
    assert cp.created_at > 0
    loaded = store.load("turn_1")
    assert loaded is not None
    assert loaded.thread_id == "t1"
    assert loaded.created_at == cp.created_at


def test_list_for_thread_filters_by_owner(store: TurnCheckpointStore, tmp_path: Path) -> None:
    store.begin_turn("turn_a", None, head=None, is_git=False, thread_id="t1")
    store.begin_turn("turn_b", None, head=None, is_git=False, thread_id="t2")
    # Hand-written checkpoints with deterministic creation times.
    for turn_id, ts in (("turn_old", 100.0), ("turn_new", 200.0)):
        (tmp_path / "checkpoints" / f"{turn_id}.json").write_text(
            json.dumps(
                {
                    "turn_id": turn_id,
                    "is_git": False,
                    "thread_id": "t1",
                    "created_at": ts,
                    "pre_contents": {},
                    "mutated": [],
                }
            ),
            encoding="utf-8",
        )

    cps = store.list_for_thread("t1")

    assert [cp.turn_id for cp in cps] == ["turn_old", "turn_new", "turn_a"]


def test_load_tolerates_legacy_format(store: TurnCheckpointStore, tmp_path: Path) -> None:
    # Checkpoints written before thread_id / created_at / post_contents existed.
    (tmp_path / "checkpoints" / "turn_legacy.json").write_text(
        json.dumps(
            {
                "turn_id": "turn_legacy",
                "is_git": False,
                "head": None,
                "pre_contents": {},
                "mutated": ["x.py"],
            }
        ),
        encoding="utf-8",
    )

    legacy = store.load("turn_legacy")

    assert legacy is not None
    assert legacy.thread_id == ""
    assert legacy.created_at == 0.0
    assert legacy.mutated == ["x.py"]
    assert legacy.has_post_images is False
    assert legacy.post_signatures == {}
    assert legacy.post_signatures_captured is False


def test_begin_turn_is_post_image_aware(store: TurnCheckpointStore) -> None:
    cp = store.begin_turn("turn_1", None, head=None, is_git=False)
    assert cp.has_post_images is True
    loaded = store.load("turn_1")
    assert loaded is not None
    assert loaded.has_post_images is True
    assert loaded.post_signatures_captured is False


@pytest.mark.asyncio
async def test_legacy_checkpoint_still_unconditionally_restores_tool_write(
    store: TurnCheckpointStore, tmp_path: Path
) -> None:
    """JSON without a ``post_contents`` field keeps the historical write."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "f.py").write_text("new\n", encoding="utf-8")
    (tmp_path / "checkpoints" / "turn_legacy.json").write_text(
        json.dumps(
            {
                "turn_id": "turn_legacy",
                "is_git": False,
                "head": None,
                "pre_contents": {"f.py": "old\n"},
                "mutated": ["f.py"],
            }
        ),
        encoding="utf-8",
    )

    report = await store.restore(["turn_legacy"], ws)

    assert report.restored == ["f.py"]
    assert report.conflicted == []
    assert (ws / "f.py").read_text(encoding="utf-8") == "old\n"


@pytest.mark.asyncio
async def test_new_checkpoint_missing_post_image_conflicts_not_blind_write(
    store: TurnCheckpointStore, tmp_path: Path
) -> None:
    """Post-image-aware checkpoint with no capture must not clobber disk."""
    ws = tmp_path / "ws"
    ws.mkdir()
    store.begin_turn("turn_1", None, head=None, is_git=False)
    store.record_pre_write("turn_1", "f.py", "old\n")
    # Simulate capture failure / unreadable skip: no record_post_images.
    (ws / "f.py").write_text("someone else\n", encoding="utf-8")

    report = await store.restore(["turn_1"], ws)

    assert report.restored == []
    assert report.conflicted == ["f.py"]
    assert (ws / "f.py").read_text(encoding="utf-8") == "someone else\n"


def test_begin_turn_records_execution_root(store: TurnCheckpointStore) -> None:
    cp = store.begin_turn(
        "turn_1",
        None,
        head=None,
        is_git=False,
        execution_root="/tmp/isolate",
    )
    assert cp.execution_root == "/tmp/isolate"
    loaded = store.load("turn_1")
    assert loaded is not None
    assert loaded.execution_root == "/tmp/isolate"


@pytest.mark.asyncio
async def test_restore_writes_recorded_root_not_fallback(
    store: TurnCheckpointStore, tmp_path: Path
) -> None:
    isolate = tmp_path / "isolate"
    project = tmp_path / "project"
    isolate.mkdir()
    project.mkdir()
    (isolate / "f.py").write_text("isolate-new\n", encoding="utf-8")
    (project / "f.py").write_text("project-now\n", encoding="utf-8")
    store.begin_turn(
        "turn_1", None, head=None, is_git=False, execution_root=str(isolate)
    )
    store.record_pre_write("turn_1", "f.py", "isolate-old\n")
    store.record_post_images("turn_1", isolate)

    report = await store.restore(["turn_1"], project)

    assert report.restored == ["f.py"]
    assert (isolate / "f.py").read_text(encoding="utf-8") == "isolate-old\n"
    assert (project / "f.py").read_text(encoding="utf-8") == "project-now\n"


@pytest.mark.asyncio
async def test_staged_project_provenance_survives_retry_and_restore(
    store: TurnCheckpointStore, tmp_path: Path
) -> None:
    isolate = tmp_path / "isolate"
    project = tmp_path / "project"
    isolate.mkdir()
    project.mkdir()
    (isolate / "f.py").write_text("agent-post\n", encoding="utf-8")
    (project / "f.py").write_text("agent-post\n", encoding="utf-8")
    store.begin_turn(
        "turn_1", None, head=None, is_git=False, execution_root=str(isolate)
    )
    store.record_pre_write("turn_1", "f.py", "pre\n")
    store.record_post_images("turn_1", isolate)
    store.retarget_to_project("turn_1", project, {"f.py": ("pre\n", "agent-post\n")})
    store.mark_publish_applied("turn_1")
    # A retry sees the already-written project bytes. They must not replace
    # the original pre-publish image saved by the first staging pass.
    store.retarget_to_project(
        "turn_1", project, {"f.py": ("agent-post\n", "agent-post\n")}
    )
    staged = store.load("turn_1")
    assert staged is not None
    assert staged.publish_pending_sync is True
    assert staged.publish_apply_complete is True
    assert staged.pre_contents["f.py"] == "pre\n"
    store.mark_publish_synced("turn_1")
    (isolate / "f.py").write_text("isolate-later\n", encoding="utf-8")

    report = await store.restore(["turn_1"], isolate)

    assert report.restored == ["f.py"]
    assert (project / "f.py").read_text(encoding="utf-8") == "pre\n"
    assert (isolate / "f.py").read_text(encoding="utf-8") == "isolate-later\n"
    completed = store.load("turn_1")
    assert completed is not None
    assert completed.publish_pending_sync is False
    assert completed.publish_apply_complete is False


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
@pytest.mark.asyncio
async def test_published_chmod_checkpoint_restores_project_mode(
    store: TurnCheckpointStore, tmp_path: Path
) -> None:
    isolate = tmp_path / "isolate"
    project = tmp_path / "project"
    isolate.mkdir()
    project.mkdir()
    for root in (isolate, project):
        (root / "run.sh").write_text("echo ok\n", encoding="utf-8")
        (root / "run.sh").chmod(0o644)
    store.begin_turn(
        "turn_mode",
        None,
        head=None,
        is_git=False,
        execution_root=str(isolate),
    )
    store.record_pre_write("turn_mode", "run.sh", "echo ok\n")
    (isolate / "run.sh").chmod(0o755)
    store.record_post_images("turn_mode", isolate)

    store.retarget_to_project(
        "turn_mode", project, {"run.sh": ("echo ok\n", "echo ok\n")}
    )
    (project / "run.sh").chmod(0o755)
    store.mark_publish_applied("turn_mode")
    store.mark_publish_synced("turn_mode")

    report = await store.restore(["turn_mode"], isolate)

    assert report.restored == ["run.sh"]
    assert (project / "run.sh").stat().st_mode & 0o777 == 0o644


@pytest.mark.asyncio
async def test_restore_skips_missing_recorded_root(
    store: TurnCheckpointStore, tmp_path: Path
) -> None:
    gone = tmp_path / "gone-isolate"
    project = tmp_path / "project"
    project.mkdir()
    (project / "f.py").write_text("project\n", encoding="utf-8")
    store.begin_turn(
        "turn_1", None, head=None, is_git=False, execution_root=str(gone)
    )
    store.record_pre_write("turn_1", "f.py", "old\n")

    report = await store.restore(["turn_1"], project)

    assert report.restored == []
    assert report.missing_roots == [str(gone)]
    assert (project / "f.py").read_text(encoding="utf-8") == "project\n"


@pytest.mark.asyncio
async def test_restore_rolls_back_whole_batch_when_one_write_fails(
    store: TurnCheckpointStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.py").write_text("new-a\n", encoding="utf-8")
    (ws / "b.py").write_text("new-b\n", encoding="utf-8")
    store.begin_turn("turn_1", None, head=None, is_git=False)
    store.record_pre_write("turn_1", "a.py", "old-a\n")
    store.record_pre_write("turn_1", "b.py", "old-b\n")
    store.record_post_images("turn_1", ws)
    original = checkpoint_module._write_pre_image

    def flaky_write(
        root: Path, rel: str, content: str | None, mode=checkpoint_module._MISSING
    ) -> None:
        if rel == "b.py" and content == "old-b\n":
            raise OSError("simulated second write failure")
        original(root, rel, content, mode)

    monkeypatch.setattr(checkpoint_module, "_write_pre_image", flaky_write)

    report = await store.restore(["turn_1"], ws)

    assert report.restored == []
    assert report.skipped == ["a.py", "b.py"]
    assert (ws / "a.py").read_text(encoding="utf-8") == "new-a\n"
    assert (ws / "b.py").read_text(encoding="utf-8") == "new-b\n"


@pytest.mark.asyncio
async def test_restore_rechecks_disk_after_planning_before_any_write(
    store: TurnCheckpointStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    target = ws / "f.py"
    target.write_text("turn\n", encoding="utf-8")
    store.begin_turn("turn_1", None, head=None, is_git=False)
    store.record_pre_write("turn_1", "f.py", "old\n")
    store.record_post_images("turn_1", ws)
    real_plan = store._plan

    async def plan_then_external_edit(*args, **kwargs):
        planned = await real_plan(*args, **kwargs)
        target.write_text("third-party\n", encoding="utf-8")
        return planned

    monkeypatch.setattr(store, "_plan", plan_then_external_edit)

    report = await store.restore(["turn_1"], ws)

    assert report.restored == []
    assert report.conflicted == ["f.py"]
    assert target.read_text(encoding="utf-8") == "third-party\n"


@pytest.mark.asyncio
async def test_restore_preserves_edit_that_lands_during_batch_write(
    store: TurnCheckpointStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    first = ws / "a.py"
    second = ws / "b.py"
    first.write_text("new-a\n", encoding="utf-8")
    second.write_text("new-b\n", encoding="utf-8")
    store.begin_turn("turn_1", None, head=None, is_git=False)
    store.record_pre_write("turn_1", "a.py", "old-a\n")
    store.record_pre_write("turn_1", "b.py", "old-b\n")
    store.record_post_images("turn_1", ws)
    original = checkpoint_module._write_pre_image

    def edit_after_second_write(
        root: Path, rel: str, content: str | None, mode=checkpoint_module._MISSING
    ) -> None:
        original(root, rel, content, mode)
        if rel == "b.py" and content == "old-b\n":
            first.write_text("third-party\n", encoding="utf-8")

    monkeypatch.setattr(
        checkpoint_module, "_write_pre_image", edit_after_second_write
    )

    report = await store.restore(["turn_1"], ws)

    assert report.restored == []
    assert report.conflicted == ["a.py", "b.py"]
    assert first.read_text(encoding="utf-8") == "third-party\n"
    assert second.read_text(encoding="utf-8") == "new-b\n"


@pytest.mark.skipif(os.name == "nt", reason="symlink creation needs privileges on Windows")
@pytest.mark.asyncio
async def test_restore_never_follows_a_symlink_and_deletes_its_target(
    store: TurnCheckpointStore, tmp_path: Path
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    valuable = workspace / "valuable.txt"
    valuable.write_text("keep me\n", encoding="utf-8")
    os.symlink("valuable.txt", workspace / "link")
    store._save(
        TurnCheckpoint(
            turn_id="turn_symlink",
            is_git=False,
            thread_id="thread_one",
            created_at=1.0,
            execution_root=str(workspace),
            mutated=["link"],
            uncertain=["link"],
            pre_contents={"link": None},
            post_contents={"link": "keep me\n"},
        )
    )

    report = await store.restore(["turn_symlink"], workspace)

    assert report.conflicted == ["link"]
    assert (workspace / "link").is_symlink()
    assert valuable.read_text(encoding="utf-8") == "keep me\n"


def test_prune_preserves_protected_live_checkpoint(store: TurnCheckpointStore) -> None:
    store._save(
        TurnCheckpoint(
            turn_id="turn_live",
            is_git=False,
            thread_id="thr_live",
            created_at=1.0,
        )
    )
    sidecars = store._raw_sidecar_dir("turn_live")
    sidecars.mkdir()
    (sidecars / "payload.post").write_bytes(b"durable")

    assert store.prune_older_than(
        1, protected_turn_ids={"turn_live"}
    ) == 0
    assert store.load("turn_live") is not None
    assert store.prune_older_than(1) == 1
    assert store.load("turn_live") is None
    assert not sidecars.exists()


@pytest.mark.skipif(os.name == "nt", reason="symlink creation needs privileges")
@pytest.mark.asyncio
async def test_raw_sidecars_publish_and_restore_exact_path_images(
    store: TurnCheckpointStore, tmp_path: Path
) -> None:
    project = tmp_path / "project"
    isolate = tmp_path / "isolate"
    project.mkdir()
    isolate.mkdir()
    (project / "blob.bin").write_bytes(b"\0project")
    (isolate / "blob.bin").write_bytes(b"\0task")
    os.symlink("project-target", project / "link")
    os.symlink("task-target", isolate / "link")
    (isolate / "created.bin").write_bytes(b"\0created")
    (project / "deleted.bin").write_bytes(b"\0deleted")
    paths = ["blob.bin", "link", "created.bin", "deleted.bin"]
    store._save(
        TurnCheckpoint(
            turn_id="turn_raw",
            is_git=False,
            thread_id="thread_one",
            created_at=1.0,
            execution_root=str(isolate),
            mutated=paths,
        )
    )
    store.record_post_images("turn_raw", isolate)
    checkpoint = store.load("turn_raw")
    assert checkpoint is not None

    store.retarget_to_project(
        "turn_raw",
        project,
        {},
        raw_source_root=isolate,
        raw_paths=paths,
        expected_raw_post_signatures=checkpoint.post_signatures,
    )

    staged = store.load("turn_raw")
    assert staged is not None
    assert staged.publish_pending_sync is True
    assert set(staged.raw_pre_images) == set(paths)
    assert set(staged.raw_post_images) == set(paths)
    pre_images, post_images = store.raw_publish_images("turn_raw", paths)
    assert all(
        image.payload_path is None or image.payload_path.is_file()
        for image in [*pre_images, *post_images]
    )

    published = await managed_worktree.apply_raw_path_images(
        project, pre_images, post_images, target="post"
    )
    assert published.applied == sorted(paths)
    assert (project / "blob.bin").read_bytes() == b"\0task"
    assert os.readlink(project / "link") == "task-target"
    assert (project / "created.bin").read_bytes() == b"\0created"
    assert not (project / "deleted.bin").exists()
    store.mark_publish_applied("turn_raw")
    store.mark_publish_synced("turn_raw")

    restored = await store.restore(["turn_raw"], isolate)

    assert restored.restored == sorted(paths)
    assert restored.conflicted == []
    assert (project / "blob.bin").read_bytes() == b"\0project"
    assert os.readlink(project / "link") == "project-target"
    assert not (project / "created.bin").exists()
    assert (project / "deleted.bin").read_bytes() == b"\0deleted"


def test_raw_sidecar_staging_rejects_directories_before_project_write(
    store: TurnCheckpointStore, tmp_path: Path
) -> None:
    project = tmp_path / "project"
    isolate = tmp_path / "isolate"
    project.mkdir()
    isolate.mkdir()
    (isolate / "node").mkdir()
    store._save(
        TurnCheckpoint(
            turn_id="turn_dir",
            is_git=False,
            thread_id="thread_one",
            created_at=1.0,
            execution_root=str(isolate),
            mutated=["node"],
        )
    )
    store.record_post_images("turn_dir", isolate)
    checkpoint = store.load("turn_dir")
    assert checkpoint is not None

    with pytest.raises(RawCheckpointError, match="directories and special"):
        store.retarget_to_project(
            "turn_dir",
            project,
            {},
            raw_source_root=isolate,
            raw_paths=["node"],
            expected_raw_post_signatures=checkpoint.post_signatures,
        )

    unstaged = store.load("turn_dir")
    assert unstaged is not None
    assert unstaged.publish_pending_sync is False
    assert unstaged.execution_root == str(isolate)
    assert not store._raw_sidecar_dir("turn_dir").exists()
    assert not (project / "node").exists()


@pytest.mark.asyncio
async def test_keep_project_retires_only_rejected_checkpoint_paths(
    store: TurnCheckpointStore, tmp_path: Path
) -> None:
    project = tmp_path / "project"
    isolate = tmp_path / "isolate"
    project.mkdir()
    isolate.mkdir()
    (project / "published.py").write_text("before\n", encoding="utf-8")
    (project / "rejected.py").write_text("keep\n", encoding="utf-8")
    (project / "rejected.bin").write_bytes(b"\0keep")
    (isolate / "published.py").write_text("published\n", encoding="utf-8")
    (isolate / "rejected.py").write_text("task\n", encoding="utf-8")
    (isolate / "rejected.bin").write_bytes(b"\0task")
    paths = ["published.py", "rejected.py", "rejected.bin"]
    store._save(
        TurnCheckpoint(
            turn_id="turn_keep",
            is_git=False,
            thread_id="thread_one",
            created_at=1.0,
            execution_root=str(isolate),
            mutated=paths,
        )
    )
    store.record_post_images("turn_keep", isolate)
    checkpoint = store.load("turn_keep")
    assert checkpoint is not None
    store.retarget_to_project(
        "turn_keep",
        project,
        {
            "published.py": ("before\n", "published\n"),
            "rejected.py": ("keep\n", "task\n"),
        },
        raw_source_root=isolate,
        raw_paths=["rejected.bin"],
        expected_raw_post_signatures=checkpoint.post_signatures,
    )
    (project / "published.py").write_text("published\n", encoding="utf-8")

    store.mark_recovery_resolved(
        "turn_keep",
        project,
        abandon_paths=["rejected.py", "rejected.bin"],
    )

    retired = store.load("turn_keep")
    assert retired is not None
    assert retired.mutated == ["published.py"]
    assert retired.raw_pre_images == {}
    assert retired.raw_post_images == {}
    assert not store._raw_sidecar_dir("turn_keep").exists()
    # Later unrelated edits happen to equal the old task images. They must not
    # resurrect the explicitly rejected task change during rewind.
    (project / "rejected.py").write_text("task\n", encoding="utf-8")
    (project / "rejected.bin").write_bytes(b"\0task")

    report = await store.restore(["turn_keep"], isolate)

    assert report.restored == ["published.py"]
    assert (project / "published.py").read_text(encoding="utf-8") == "before\n"
    assert (project / "rejected.py").read_text(encoding="utf-8") == "task\n"
    assert (project / "rejected.bin").read_bytes() == b"\0task"
