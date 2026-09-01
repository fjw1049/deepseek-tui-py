import { describe, expect, it } from 'vitest'
import type { ChatBlock } from '../agent/types'
import {
  editedRowsFromToolBlocks,
  indexTurnDiffSnapshots,
  resolveLatestTurnDiffId,
  resolveTurnDiffId,
  toolBlocksFromTurnSummary,
  turnSummaryFromSources,
  type TurnDiffSnapshot
} from './turn-mutation-view'

describe('turn-mutation-view', () => {
  it('builds edited rows only from file_change tools', () => {
    const blocks: ChatBlock[] = [
      {
        kind: 'tool',
        id: 't1',
        summary: 'edit_file: path="a.ts"',
        status: 'success',
        toolKind: 'file_change',
        filePath: 'a.ts',
        detail: 'diff --git a/a.ts b/a.ts\n--- a/a.ts\n+++ b/a.ts\n@@\n-a\n+b\n'
      },
      {
        kind: 'tool',
        id: 't2',
        summary: 'exec_shell: sed',
        status: 'success',
        toolKind: 'command_execution',
        detail: 'ok'
      }
    ]
    const rows = editedRowsFromToolBlocks(blocks)
    expect(rows).toHaveLength(1)
    expect(rows[0]?.path).toBe('a.ts')
  })

  it('prefers turn.diff snapshot over tool blocks', () => {
    const summary = turnSummaryFromSources(
      {
        turn_id: 'turn_1',
        files: [
          {
            path: 'from-ledger.py',
            additions: 2,
            deletions: 1,
            unified_diff:
              'diff --git a/from-ledger.py b/from-ledger.py\n--- a/from-ledger.py\n+++ b/from-ledger.py\n@@\n-a\n+b\n+c\n'
          }
        ],
        totals: { files: 1, additions: 2, deletions: 1 },
        revision: 3,
        complete: false
      },
      []
    )
    expect(summary.files[0]?.path).toBe('from-ledger.py')
    const tools = toolBlocksFromTurnSummary('turn_1', summary)
    expect(tools[0]?.toolKind).toBe('file_change')
    expect(tools[0]?.filePath).toBe('from-ledger.py')
  })

  it('retains ledger summary after currentTurnId is cleared (post-complete)', () => {
    // Mimics chat-store: onTurnComplete nulls currentTurnId but keeps
    // lastCompletedTurnId + turnDiffByTurnId[turnId].
    const turnId = 'turn_done'
    const byId: Record<string, TurnDiffSnapshot> = {
      [turnId]: {
        turn_id: turnId,
        files: [
          {
            path: 'reconcile-only.py',
            additions: 1,
            deletions: 0,
            unified_diff:
              'diff --git a/reconcile-only.py b/reconcile-only.py\n--- /dev/null\n+++ b/reconcile-only.py\n@@\n+x\n'
          }
        ],
        totals: { files: 1, additions: 1, deletions: 0 },
        revision: 4,
        complete: true
      }
    }
    const resolved = resolveLatestTurnDiffId(null, turnId)
    expect(resolved).toBe(turnId)
    const snap = resolved ? byId[resolved] : undefined
    const summary = turnSummaryFromSources(snap, [])
    expect(summary.files).toHaveLength(1)
    expect(summary.files[0]?.path).toBe('reconcile-only.py')
    const tools = toolBlocksFromTurnSummary(resolved!, summary)
    expect(tools).toHaveLength(1)
  })

  it('prefers live currentTurnId over lastCompletedTurnId', () => {
    expect(resolveLatestTurnDiffId('turn_live', 'turn_old')).toBe('turn_live')
    expect(resolveLatestTurnDiffId(null, 'turn_old')).toBe('turn_old')
    expect(resolveLatestTurnDiffId(null, null)).toBeNull()
  })

  it('keeps an older timeline turn bound to its own durable snapshot', () => {
    expect(resolveTurnDiffId('turn_old', false, 'turn_live', 'turn_done')).toBe('turn_old')
    expect(resolveTurnDiffId(undefined, false, 'turn_live', 'turn_done')).toBeNull()
  })

  it('treats an empty snapshot as authoritative after a full revert', () => {
    const summary = turnSummaryFromSources(
      {
        turn_id: 'turn_reverted',
        files: [],
        totals: { files: 0, additions: 0, deletions: 0 },
        revision: 3,
        complete: true
      },
      [
        {
          kind: 'tool',
          id: 'edit-before-revert',
          summary: 'edit_file: path="a.ts"',
          status: 'success',
          toolKind: 'file_change',
          filePath: 'a.ts',
          detail: 'diff --git a/a.ts b/a.ts\n--- a/a.ts\n+++ b/a.ts\n@@\n-old\n+new\n'
        }
      ]
    )
    expect(summary.files).toHaveLength(0)
    expect(summary.totals).toEqual({ files: 0, additions: 0, deletions: 0 })
  })

  it('indexes persisted snapshots when a thread is reopened', () => {
    const indexed = indexTurnDiffSnapshots([
      {
        turn_id: 'turn_saved',
        files: [],
        totals: { files: 0, additions: 0, deletions: 0 },
        revision: 2,
        complete: true
      }
    ])
    expect(indexed.turn_saved?.complete).toBe(true)
    expect(indexed.turn_saved?.files).toEqual([])
  })

  it('reconciles totals from unique files so header matches the list', () => {
    const summary = turnSummaryFromSources(
      {
        turn_id: 'turn_1',
        files: [
          {
            path: 'a.ts',
            additions: 6,
            deletions: 3,
            unified_diff: 'diff --git a/a.ts b/a.ts\n--- a/a.ts\n+++ b/a.ts\n@@\n-a\n+b\n'
          },
          {
            path: 'b.ts',
            additions: 5,
            deletions: 0,
            unified_diff: 'diff --git a/b.ts b/b.ts\n--- a/b.ts\n+++ b/b.ts\n@@\n+x\n'
          }
        ],
        totals: { files: 99, additions: 1, deletions: 1 },
        revision: 1,
        complete: true
      },
      []
    )
    expect(summary.totals).toEqual({ files: 2, additions: 11, deletions: 3 })
    expect(toolBlocksFromTurnSummary('turn_1', summary)).toHaveLength(2)
  })

  it('merges repeated tool edits of the same path in the fallback', () => {
    const patch = 'diff --git a/a.ts b/a.ts\n--- a/a.ts\n+++ b/a.ts\n@@\n-a\n+b\n'
    const summary = turnSummaryFromSources(null, [
      {
        kind: 'tool',
        id: 't1',
        summary: 'edit_file: path="a.ts"',
        status: 'success',
        toolKind: 'file_change',
        filePath: 'a.ts',
        detail: patch
      },
      {
        kind: 'tool',
        id: 't2',
        summary: 'edit_file: path="a.ts"',
        status: 'success',
        toolKind: 'file_change',
        filePath: 'a.ts',
        detail: patch
      }
    ])
    expect(summary.files).toHaveLength(1)
    expect(summary.totals.files).toBe(1)
  })
})
