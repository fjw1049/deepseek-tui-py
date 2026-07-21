import { describe, expect, it } from 'vitest'
import type { ChatBlock } from '../agent/types'
import {
  editedRowsFromToolBlocks,
  resolveLatestTurnDiffId,
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
})
