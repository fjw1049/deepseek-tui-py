"""Per-turn file checkpoints — record / restore semantics."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from deepseek_tui.workspace.shell_mutation_watch import ShellMutationSnapshot
from deepseek_tui.workspace.turn_checkpoints import TurnCheckpointStore


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
    store.begin_turn("turn_2", None, head=None, is_git=False)
    store.record_pre_write("turn_2", "f.py", "v2\n")
    (ws / "f.py").write_text("v3\n", encoding="utf-8")

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

    report = await store.restore(["turn_1"], git_repo)

    assert (git_repo / "tracked.py").read_text(encoding="utf-8") == "v1\n"
    assert report.restored == ["tracked.py"]


@pytest.mark.asyncio
async def test_restore_git_show_failure_means_file_did_not_exist(
    store: TurnCheckpointStore, git_repo: Path
) -> None:
    head = _git(git_repo, "rev-parse", "HEAD")
    store.begin_turn("turn_1", None, head=head, is_git=True)
    store.record_out_of_band("turn_1", "created_by_shell.py")
    (git_repo / "created_by_shell.py").write_text("new\n", encoding="utf-8")

    report = await store.restore(["turn_1"], git_repo)

    assert not (git_repo / "created_by_shell.py").exists()
    assert report.restored == ["created_by_shell.py"]


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
    store.begin_turn("turn_2", None, head=None, is_git=False)
    store.record_out_of_band("turn_2", "f.py")
    (ws / "f.py").write_text("v3\n", encoding="utf-8")

    report = await store.restore(["turn_2", "turn_1"], ws)

    assert (ws / "f.py").read_text(encoding="utf-8") == "v1\n"
    assert report.restored == ["f.py"]
    assert report.skipped == []


def test_delete_removes_checkpoint(store: TurnCheckpointStore) -> None:
    store.begin_turn("turn_1", None, head=None, is_git=False)
    store.delete("turn_1")
    assert store.load("turn_1") is None
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
    # Checkpoints written before thread_id / created_at existed still load.
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
