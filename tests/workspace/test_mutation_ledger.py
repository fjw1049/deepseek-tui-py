"""Unit tests for File Mutation Ledger core modules."""

from __future__ import annotations

from pathlib import Path

from deepseek_tui.workspace.diff_synth import count_diff_stats, synthesize_unified_diff
from deepseek_tui.workspace.mutation_ledger import (
    FileMutation,
    TurnMutationLedger,
    build_mutation_metadata,
    mutation_from_metadata,
)
from deepseek_tui.workspace.shell_write_guard import check_shell_write, is_allowlisted_path


def test_synthesize_unified_diff_update() -> None:
    unified, stats, op = synthesize_unified_diff(
        "src/foo.py", "hello\n", "hello\nworld\n"
    )
    assert op == "update"
    assert "diff --git" in unified
    assert "+world" in unified
    assert stats.additions >= 1


def test_synthesize_unified_diff_create() -> None:
    unified, stats, op = synthesize_unified_diff("notes.md", "", "hi\n")
    assert op == "create"
    assert "--- /dev/null" in unified
    assert stats.additions >= 1


def test_ledger_folds_by_path() -> None:
    ledger = TurnMutationLedger("turn_1", throttle_ms=0)
    ledger.commit(
        FileMutation(
            mutation_id="m1",
            turn_id="turn_1",
            path="a.py",
            op="create",
            unified_diff="diff --git a/a.py b/a.py\n--- /dev/null\n+++ b/a.py\n@@\n+x\n",
            additions=1,
            deletions=0,
            source="write_file",
        ),
        emit=False,
    )
    ledger.commit(
        FileMutation(
            mutation_id="m2",
            turn_id="turn_1",
            path="a.py",
            op="update",
            unified_diff="diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@\n-x\n+y\n",
            additions=1,
            deletions=1,
            source="edit_file",
        ),
        emit=False,
    )
    snap = ledger.snapshot()
    assert snap.totals["files"] == 1
    assert snap.files[0].path == "a.py"
    assert snap.files[0].op == "update"
    assert "+y" in snap.files[0].unified_diff


def test_mutation_from_metadata() -> None:
    meta = {
        "path": "src/a.py",
        "mutation": {
            "path": "src/a.py",
            "op": "update",
            "unified_diff": "diff --git a/src/a.py b/src/a.py\n--- a/src/a.py\n+++ b/src/a.py\n@@\n-a\n+b\n",
            "additions": 1,
            "deletions": 1,
            "source": "edit_file",
        },
    }
    muts = mutation_from_metadata(meta, turn_id="t1", tool_call_id="tc1")
    assert len(muts) == 1
    assert muts[0].path == "src/a.py"
    assert muts[0].source == "edit_file"
    assert count_diff_stats(muts[0].unified_diff).additions == 1


def test_build_mutation_metadata_line_start_roundtrip() -> None:
    meta = build_mutation_metadata(
        path="src/a.py",
        op="update",
        unified_diff="diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@\n-a\n+b\n",
        additions=1,
        deletions=1,
        source="edit_file",
        line_start=7,
    )
    assert meta["mutation"]["line_start"] == 7
    muts = mutation_from_metadata(meta, turn_id="t1")
    assert len(muts) == 1
    assert muts[0].line_start == 7
    assert muts[0].to_dict()["line_start"] == 7

    # Absent line_start is tolerated and stays None.
    meta_none = build_mutation_metadata(
        path="src/a.py",
        op="update",
        unified_diff="",
        additions=0,
        deletions=0,
        source="edit_file",
    )
    assert "line_start" not in meta_none["mutation"]
    muts_none = mutation_from_metadata(meta_none, turn_id="t1")
    assert len(muts_none) == 1
    assert muts_none[0].line_start is None


def test_snapshot_dict_includes_line_start() -> None:
    ledger = TurnMutationLedger("turn_ls", throttle_ms=0)
    ledger.commit(
        FileMutation(
            mutation_id="m1",
            turn_id="turn_ls",
            path="a.py",
            op="update",
            unified_diff="diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@\n-a\n+b\n",
            additions=1,
            deletions=1,
            source="edit_file",
            line_start=5,
        ),
        emit=False,
    )
    snap_dict = ledger.snapshot().to_dict()
    assert snap_dict["files"][0]["line_start"] == 5


def test_shell_detected_mutation_roundtrip() -> None:
    # Shape produced by shell_mutation_watch.detect_shell_mutations.
    detected = {
        "path": "b.py",
        "op": "update",
        "unified_diff": "diff --git a/b.py b/b.py\n--- a/b.py\n+++ b/b.py\n@@\n-x\n+y\n",
        "additions": 1,
        "deletions": 1,
        "source": "shell_detected",
        "status": "applied",
        "line_start": 3,
    }
    muts = mutation_from_metadata(
        {"mutation": detected, "path": detected["path"]},
        turn_id="t1",
        tool_call_id="tc_shell",
        source_fallback="shell_detected",
    )
    assert len(muts) == 1
    assert muts[0].source == "shell_detected"
    assert muts[0].line_start == 3

    ledger = TurnMutationLedger("t1", throttle_ms=0)
    ledger.commit(muts[0], emit=False)
    assert ledger.covered_paths() == {"b.py"}
    snap_dict = ledger.snapshot().to_dict()
    assert snap_dict["files"][0]["path"] == "b.py"
    assert snap_dict["files"][0]["line_start"] == 3
    assert snap_dict["totals"] == {"files": 1, "additions": 1, "deletions": 1}


def test_shell_write_guard_denies_sed_inplace() -> None:
    v = check_shell_write("sed -i 's/foo/bar/' src/main.py")
    assert not v.allowed
    assert "edit_file" in v.reason


def test_shell_write_guard_denies_heredoc_source() -> None:
    v = check_shell_write("cat > src/foo.py <<'EOF'\nprint(1)\nEOF")
    assert not v.allowed


def test_shell_write_guard_allows_scratch() -> None:
    v = check_shell_write("cat > scratch/demo.py <<'EOF'\nprint(1)\nEOF")
    assert v.allowed


def test_shell_write_guard_allows_pytest() -> None:
    v = check_shell_write("pytest tests/ -q")
    assert v.allowed


def test_allowlist_tmp() -> None:
    assert is_allowlisted_path("/tmp/out.txt")
    assert is_allowlisted_path("scratch/x.py")
    assert not is_allowlisted_path("src/x.py")


def test_ledger_throttle_and_flush() -> None:
    emitted: list[int] = []
    ledger = TurnMutationLedger(
        "turn_t",
        throttle_ms=10_000,
        on_snapshot=lambda snap: emitted.append(snap.revision),
    )
    ledger.commit(
        FileMutation(
            mutation_id="m1",
            turn_id="turn_t",
            path="a.py",
            op="update",
            unified_diff="diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@\n-a\n+b\n",
            additions=1,
            deletions=1,
            source="edit_file",
        ),
        emit=True,
    )
    # First emit always goes through (last_emit was 0).
    assert len(emitted) == 1
    ledger.commit(
        FileMutation(
            mutation_id="m2",
            turn_id="turn_t",
            path="b.py",
            op="create",
            unified_diff="diff --git a/b.py b/b.py\n--- /dev/null\n+++ b/b.py\n@@\n+z\n",
            additions=1,
            deletions=0,
            source="write_file",
        ),
        emit=True,
    )
    # Throttled — pending
    assert len(emitted) == 1
    ledger.flush()
    assert len(emitted) == 2
