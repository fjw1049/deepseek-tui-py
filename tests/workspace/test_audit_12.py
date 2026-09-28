"""Offline regression cases for workspace audit 12."""

import asyncio
import subprocess
from unittest.mock import patch

import pytest

from deepseek_tui.workspace import diff_synth as ds, git_reconcile as gr
from deepseek_tui.workspace import managed_worktree as mw, mutation_ledger as ml
from deepseek_tui.workspace.shell_write_guard import is_allowlisted_path
from deepseek_tui.workspace.turn_checkpoints import TurnCheckpoint, TurnCheckpointStore


def git(root, *args, input=None):
    return subprocess.run(
        ["git", "-C", str(root), *args], input=input, check=True, capture_output=True
    ).stdout


def repo(root):
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "config", "user.name", "Fixture")
    for name in ["a.txt", "b.txt", "中文.txt"]:
        (root / name).write_text("base\n")
    (root / "raw.bin").write_bytes(b"\0base")
    git(root, "add", ".")
    git(root, "commit", "-qm", "base")
    return root


def mutation(path, status="applied"):
    return ml.FileMutation(path, "turn", path, "update", "", 0, 0, "write_file", status)


@pytest.mark.parametrize("name", [".env", "a b", "中文.txt", "a\\b", "a\nb", 'a"b'])
@pytest.mark.parametrize("before,after", [("old", "new"), ("old\n", "new"), ("--old\n", "++new\n")])
def test_patch_applies_with_exact_path(tmp_path, name, before, after):
    (tmp_path / name).write_text(before)
    diff, stats, _ = ds.synthesize_unified_diff(name, before, after, op="update")
    git(tmp_path, "apply", "--check", "-", input=diff.encode())
    git(tmp_path, "apply", "-", input=diff.encode())
    assert (tmp_path / name).read_text() == after
    assert (stats.additions, stats.deletions) == (1, 1)


@pytest.mark.parametrize("status", ["failed", "pending"])
def test_unsuccessful_mutation_does_not_advance_net(status):
    ledger = ml.TurnMutationLedger("turn")
    ledger.commit(mutation("x"), before_content="a\n", after_content="b\n")
    ledger.commit(mutation("x", status), before_content="b\n", after_content="c\n")
    assert "+b\n" in ledger.snapshot().merged_unified_diff
    assert "+c\n" not in ledger.snapshot().merged_unified_diff


def test_diff_fold_only_recomputes_changed_paths():
    ledger = ml.TurnMutationLedger("turn")
    with patch.object(ml, "synthesize_unified_diff", wraps=ds.synthesize_unified_diff) as spy:
        for i in range(100):
            ledger.commit(mutation(str(i)), before_content="a\n", after_content="b\n")
        ledger.snapshot()
        assert spy.call_count == 100


def test_commit_keeps_original_full_history():
    m = mutation("x")
    m.unified_diff = "diff --git a/x b/x\n@@\n" + "+new\n" * 100
    full = m.unified_diff
    ledger = ml.TurnMutationLedger("turn", diff_max_chars=20)
    snap = ledger.commit(m)
    assert m.unified_diff == ledger.history[0].unified_diff == full
    assert snap.files[0].detail_truncated


@pytest.mark.parametrize("name", ["../escape", "/escape", "a/b", "a\\b", "", ".."])
def test_checkpoint_rejects_path_ids(tmp_path, name):
    store = TurnCheckpointStore(tmp_path)
    for operation in [
        lambda: store.begin_turn(name, None, head=None, is_git=False),
        lambda: store.load(name),
        lambda: store.delete(name),
    ]:
        with pytest.raises(ValueError):
            operation()


def test_guard_uses_resolved_workspace_membership(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "build").symlink_to(tmp_path / "src", target_is_directory=True)
    assert not is_allowlisted_path("build/../src/main.py", workspace=tmp_path)
    assert not is_allowlisted_path("build/main.py", workspace=tmp_path)
    assert not is_allowlisted_path(str(tmp_path / "src/main.py"), workspace=tmp_path)
    assert is_allowlisted_path(".deepseek/tmp/result.py", workspace=tmp_path)


async def test_handoff_does_not_drop_failed_source(tmp_path, monkeypatch):
    src, dst = repo(tmp_path / "src"), repo(tmp_path / "dst")
    for name in ["a.txt", "b.txt"]:
        (src / name).write_text("new\n")
    original = mw._write_text

    def fail(target, rel, content):
        if rel == "b.txt":
            raise OSError("fixture")
        original(target, rel, content)

    monkeypatch.setattr(mw, "_write_text", fail)
    result = await mw.handoff_changes(src, dst)
    assert "b.txt" in result.skipped
    assert (src / "b.txt").read_text() == "new\n"


async def test_handoff_rejects_binary_conflict(tmp_path):
    src, dst = repo(tmp_path / "src"), repo(tmp_path / "dst")
    (src / "raw.bin").write_bytes(b"\0source")
    (dst / "raw.bin").write_bytes(b"\0destination")
    result = await mw.handoff_changes(src, dst)
    assert result.conflicted == ["raw.bin"]
    assert (dst / "raw.bin").read_bytes() == b"\0destination"


async def test_handoff_preserves_later_source_edit(tmp_path, monkeypatch):
    src, dst = repo(tmp_path / "src"), repo(tmp_path / "dst")
    (src / "a.txt").write_text("new\n")
    original = mw._write_text

    def edit_source(target, rel, content):
        original(target, rel, content)
        (src / rel).write_text("later\n")

    monkeypatch.setattr(mw, "_write_text", edit_source)
    await mw.handoff_changes(src, dst)
    assert (src / "a.txt").read_text() == "later\n"


async def test_git_baseline_unicode_and_committed_change(tmp_path):
    root = repo(tmp_path / "repo")
    (root / "中文.txt").write_text("preexisting\n")
    baseline = await gr.capture_baseline(root)
    assert "中文.txt" in baseline.dirty_at_start
    (root / "a.txt").write_text("committed\n")
    git(root, "add", "a.txt")
    git(root, "commit", "-qm", "turn")
    found = await gr.reconcile_to_ledger(ml.TurnMutationLedger("turn"), baseline)
    assert {m.path for m in found} == {"a.txt"}


async def test_reconcile_never_reads_external_symlink(tmp_path):
    root = repo(tmp_path / "repo")
    baseline = await gr.capture_baseline(root)
    external = tmp_path / "outside"
    external.write_text("external content")
    (root / "link").symlink_to(external)
    found = await gr.reconcile_to_ledger(ml.TurnMutationLedger("turn"), baseline)
    assert not any("external content" in m.unified_diff for m in found)


async def test_cancel_mixed_restore_finishes_transaction(tmp_path, monkeypatch):
    store = TurnCheckpointStore(tmp_path / "checkpoints")
    project, isolate = tmp_path / "project", tmp_path / "isolate"
    project.mkdir()
    isolate.mkdir()
    (project / "raw").write_bytes(b"\0old")
    (isolate / "raw").write_bytes(b"\0new")
    (project / "text").write_text("old\n")
    (isolate / "text").write_text("new\n")
    store._save(
        TurnCheckpoint(
            turn_id="turn", is_git=False, execution_root=str(isolate), mutated=["raw", "text"]
        )
    )
    store.record_post_images("turn", isolate)
    cp = store.load("turn")
    store.retarget_to_project(
        "turn",
        project,
        {"text": ("old\n", "new\n")},
        raw_source_root=isolate,
        raw_paths=["raw"],
        expected_raw_post_signatures=cp.post_signatures,
    )
    pre, post = store.raw_publish_images("turn", ["raw"])
    await mw.apply_raw_path_images(project, pre, post, target="post")
    (project / "text").write_text("new\n")
    store.mark_publish_applied("turn")
    store.mark_publish_synced("turn")
    original = mw.apply_raw_path_images
    entered, release = asyncio.Event(), asyncio.Event()

    async def pause_after_write(*args, **kwargs):
        result = await original(*args, **kwargs)
        entered.set()
        await release.wait()
        return result

    monkeypatch.setattr(mw, "apply_raw_path_images", pause_after_write)
    task = asyncio.create_task(store.restore(["turn"], project))
    await asyncio.wait_for(entered.wait(), 2)
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (project / "raw").read_bytes() == b"\0old"
    assert (project / "text").read_text() == "old\n"


def test_automatic_reclaim_keeps_occupied_tree(tmp_path, monkeypatch):
    monkeypatch.setattr(mw, "_has_labor_sync", lambda p: False)
    monkeypatch.setattr(mw, "is_managed_path", lambda p: True)
    monkeypatch.setattr(mw, "_pids_with_cwd_under_sync", lambda p: [12345])

    def no_kill(*a):
        pytest.fail("automatic reclamation must not kill unknown processes")

    monkeypatch.setattr(mw, "_terminate_processes_under_sync", no_kill)
    assert not mw._remove_clean_worktree_sync(tmp_path)


@pytest.mark.parametrize(
    "op,before,after",
    [("create", "", ""), ("delete", "", ""), ("create", "", "new"), ("delete", "old", "")],
)
def test_empty_and_missing_file_patch(tmp_path, op, before, after):
    if op != "create":
        (tmp_path / ".env").write_text(before)
    diff, _, _ = ds.synthesize_unified_diff(".env", before, after, op=op)
    git(tmp_path, "apply", "-", input=diff.encode())
    if op == "delete":
        assert not (tmp_path / ".env").exists()
    else:
        assert (tmp_path / ".env").read_text() == after


async def test_reconcile_skips_oversized_text(tmp_path):
    from deepseek_tui.workspace.shell_mutation_watch import _MAX_FILE_BYTES

    root = repo(tmp_path / "repo")
    baseline = await gr.capture_baseline(root)
    (root / "large").write_bytes(b"x" * (_MAX_FILE_BYTES + 1))
    assert not await gr.reconcile_to_ledger(ml.TurnMutationLedger("turn"), baseline)


async def test_binary_head_is_not_absence(tmp_path):
    from deepseek_tui.workspace.shell_mutation_watch import _head_content, _Unreadable

    root = repo(tmp_path / "repo")
    assert isinstance(await _head_content(root, "raw.bin"), _Unreadable)
    assert await _head_content(root, "missing") is None


def test_checkpoint_rejects_mismatched_record_id(tmp_path):
    import json

    store = TurnCheckpointStore(tmp_path)
    store.begin_turn("a", None, head=None, is_git=False)
    path = tmp_path / "a.json"
    data = json.loads(path.read_text())
    data["turn_id"] = "../other"
    path.write_text(json.dumps(data))
    assert store.load("a") is None
