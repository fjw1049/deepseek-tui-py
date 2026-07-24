"""Edge cases: truncation stats, empty create, multi-path fold, metadata lists."""

from __future__ import annotations

from deepseek_tui.workspace.diff_synth import synthesize_unified_diff
from deepseek_tui.workspace.mutation_ledger import (
    DEFAULT_DIFF_MAX_CHARS,
    FileMutation,
    TurnMutationLedger,
    mutation_from_metadata,
)


def test_empty_create_classified() -> None:
    unified, stats, op = synthesize_unified_diff("empty.py", "", "")
    assert op == "create"
    assert "diff --git" in unified
    assert stats.additions == 0


def test_truncation_preserves_original_additions_deletions() -> None:
    body_lines = [f"+line_{i}\n" for i in range(5_000)]
    big = (
        "diff --git a/big.py b/big.py\n--- /dev/null\n+++ b/big.py\n@@\n"
        + "".join(body_lines)
    )
    assert len(big) > DEFAULT_DIFF_MAX_CHARS
    ledger = TurnMutationLedger("t_trunc", diff_max_chars=2_000, throttle_ms=0)
    snap = ledger.commit(
        FileMutation(
            mutation_id="m1",
            turn_id="t_trunc",
            path="big.py",
            op="create",
            unified_diff=big,
            additions=5_000,
            deletions=0,
            source="write_file",
        ),
        emit=False,
    )
    assert snap.files[0].detail_truncated
    assert len(snap.files[0].unified_diff) < len(big)
    assert snap.files[0].additions == 5_000
    assert snap.totals["additions"] == 5_000


def test_truncation_recomputes_stats_when_missing() -> None:
    body = "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@\n" + (
        "-old\n" * 200 + "+new\n" * 200
    )
    ledger = TurnMutationLedger("t_trunc2", diff_max_chars=400, throttle_ms=0)
    snap = ledger.commit(
        FileMutation(
            mutation_id="m1",
            turn_id="t_trunc2",
            path="x.py",
            op="update",
            unified_diff=body,
            additions=0,
            deletions=0,
            source="edit_file",
        ),
        emit=False,
    )
    # Stats taken from full body before truncate.
    assert snap.files[0].additions == 200
    assert snap.files[0].deletions == 200
    assert snap.files[0].detail_truncated


def test_fold_keeps_latest_diff_per_path_and_counts_files() -> None:
    ledger = TurnMutationLedger("t_fold", throttle_ms=0)
    for i, path in enumerate(["a.py", "b.py", "a.py"]):
        ledger.commit(
            FileMutation(
                mutation_id=f"m{i}",
                turn_id="t_fold",
                path=path,
                op="update" if i else "create",
                unified_diff=(
                    f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
                    f"@@\n-old{i}\n+new{i}\n"
                ),
                additions=1,
                deletions=1,
                source="edit_file",
            ),
            emit=False,
        )
    snap = ledger.snapshot()
    assert snap.totals["files"] == 2
    a = next(f for f in snap.files if f.path == "a.py")
    assert "+new2" in a.unified_diff
    assert a.op == "update"


def test_mutations_list_from_metadata() -> None:
    meta = {
        "mutations": [
            {
                "path": "a.py",
                "op": "update",
                "unified_diff": "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@\n-a\n+b\n",
                "additions": 1,
                "deletions": 1,
                "source": "edit_file",
            },
            {
                "path": "b.py",
                "op": "create",
                "unified_diff": "diff --git a/b.py b/b.py\n--- /dev/null\n+++ b/b.py\n@@\n+z\n",
                "additions": 1,
                "deletions": 0,
                "source": "edit_file",
            },
        ]
    }
    muts = mutation_from_metadata(meta, turn_id="t1", tool_call_id="patch1")
    assert len(muts) == 2
    assert {m.path for m in muts} == {"a.py", "b.py"}
    assert all(m.source == "edit_file" for m in muts)
    assert all(m.tool_call_id == "patch1" for m in muts)


def test_failed_mutations_excluded_from_fold() -> None:
    ledger = TurnMutationLedger("t_fail", throttle_ms=0)
    ledger.commit(
        FileMutation(
            mutation_id="m1",
            turn_id="t_fail",
            path="a.py",
            op="update",
            unified_diff="diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@\n-a\n+b\n",
            additions=1,
            deletions=1,
            source="edit_file",
            status="failed",
        ),
        emit=False,
    )
    snap = ledger.snapshot()
    assert snap.totals["files"] == 0
