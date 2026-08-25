import { describe, expect, it } from 'vitest'
import type { ChatBlock } from '../agent/types'
import { countDiffStats } from './diff-stats'
import {
  collectWorkspaceChangeEntries,
  sumWorkspaceChangeStats,
  turnSummaryFromWorkspaceEntries,
  workspaceChangeEntryStats
} from './workspace-change-stats'

const PATCH_A = [
  'diff --git a/a.ts b/a.ts',
  '--- a/a.ts',
  '+++ b/a.ts',
  '@@',
  '-old',
  '+new',
  '+new2'
].join('\n')

const PATCH_B = [
  'diff --git a/b.ts b/b.ts',
  '--- a/b.ts',
  '+++ b/b.ts',
  '@@',
  '+only'
].join('\n')

function fileChange(id: string, path: string, detail: string): ChatBlock {
  return {
    kind: 'tool',
    id,
    summary: `edit_file: path="${path}"`,
    status: 'success',
    toolKind: 'file_change',
    filePath: path,
    detail
  }
}

describe('collectWorkspaceChangeEntries', () => {
  it('does not double-count the same path from session + git', () => {
    const entries = collectWorkspaceChangeEntries({
      blocks: [fileChange('t1', 'a.ts', PATCH_A), fileChange('t2', 'a.ts', PATCH_A)],
      gitFiles: [{ path: 'a.ts', status: 'modified', stage: 'unstaged', patch: PATCH_A }]
    })
    expect(entries).toHaveLength(1)
    const stats = entries.map((entry) => workspaceChangeEntryStats(entry))
    expect(sumWorkspaceChangeStats(entries)).toEqual(stats[0])
  })

  it('header +/- equals the sum of per-file stats', () => {
    const entries = collectWorkspaceChangeEntries({
      blocks: [fileChange('t1', 'a.ts', PATCH_A)],
      gitFiles: [
        { path: 'a.ts', status: 'modified', stage: 'unstaged', patch: PATCH_A },
        { path: 'b.ts', status: 'added', stage: 'unstaged', patch: PATCH_B }
      ]
    })
    expect(entries).toHaveLength(2)
    const perFile = entries.map((entry) => workspaceChangeEntryStats(entry))
    const added = perFile.reduce((n, s) => n + (s?.added ?? 0), 0)
    const removed = perFile.reduce((n, s) => n + (s?.removed ?? 0), 0)
    expect(sumWorkspaceChangeStats(entries)).toEqual({ added, removed })
  })

  it('prefers the git patch once the session edit has settled', () => {
    const gitPatch = `${PATCH_A}\n+extra`
    const entries = collectWorkspaceChangeEntries({
      blocks: [fileChange('t1', 'a.ts', PATCH_A)],
      gitFiles: [{ path: 'a.ts', status: 'modified', stage: 'unstaged', patch: gitPatch }]
    })
    expect(entries).toHaveLength(1)
    expect(entries[0]?.detail).toBe(gitPatch)
    expect(entries[0]?.committable).toBe(true)
    expect(workspaceChangeEntryStats(entries[0]!)).toEqual(countDiffStats(gitPatch))
  })

  it('uses git vs HEAD +/- instead of last-edit ledger counts', () => {
    const lastEdit = [
      'diff --git a/git.py b/git.py',
      '--- a/git.py',
      '+++ b/git.py',
      '@@',
      '+timeout'
    ].join('\n')
    const vsHead = [
      'diff --git a/git.py b/git.py',
      '--- a/git.py',
      '+++ b/git.py',
      '@@',
      '+one',
      '+two',
      '+three',
      '-old'
    ].join('\n')
    const entries = collectWorkspaceChangeEntries({
      turnDiffByTurnId: {
        turn_1: {
          turn_id: 'turn_1',
          files: [
            {
              path: 'git.py',
              additions: 1,
              deletions: 0,
              unified_diff: lastEdit
            }
          ],
          totals: { files: 1, additions: 1, deletions: 0 },
          revision: 2,
          complete: true
        }
      },
      blocks: [],
      gitFiles: [{ path: 'git.py', status: 'modified', stage: 'unstaged', patch: vsHead }]
    })
    expect(sumWorkspaceChangeStats(entries)).toEqual({ added: 3, removed: 1 })
    const summary = turnSummaryFromWorkspaceEntries(entries)
    expect(summary.totals).toEqual({ files: 1, additions: 3, deletions: 1 })
    expect(summary.files[0]?.unified_diff).toBe(vsHead)
  })

  it('drops session/ledger entries whose path is no longer git-dirty (committed)', () => {
    const entries = collectWorkspaceChangeEntries({
      blocks: [fileChange('t1', 'a.ts', PATCH_A)],
      turnDiffByTurnId: {
        turn_1: {
          turn_id: 'turn_1',
          files: [{ path: 'b.ts', additions: 1, deletions: 0, unified_diff: PATCH_B }],
          totals: { files: 1, additions: 1, deletions: 0 },
          revision: 1,
          complete: true
        }
      },
      // Loaded and clean: both session paths were committed.
      gitFiles: []
    })
    expect(entries).toHaveLength(0)
  })

  it('keeps session entries when the git snapshot has not loaded yet', () => {
    const entries = collectWorkspaceChangeEntries({
      blocks: [fileChange('t1', 'a.ts', PATCH_A)],
      gitFiles: null
    })
    expect(entries).toHaveLength(1)
    expect(entries[0]?.filePath).toBe('a.ts')
  })

  it('treats a missing gitFiles argument like still-loading, not a clean tree', () => {
    const entries = collectWorkspaceChangeEntries({
      blocks: [fileChange('t1', 'a.ts', PATCH_A)]
    })
    expect(entries).toHaveLength(1)
    expect(entries[0]?.filePath).toBe('a.ts')
  })

  it('keeps still-dirty paths when only some session files were committed', () => {
    const entries = collectWorkspaceChangeEntries({
      blocks: [fileChange('t1', 'a.ts', PATCH_A)],
      turnDiffByTurnId: {
        turn_1: {
          turn_id: 'turn_1',
          files: [{ path: 'b.ts', additions: 1, deletions: 0, unified_diff: PATCH_B }],
          totals: { files: 1, additions: 1, deletions: 0 },
          revision: 1,
          complete: true
        }
      },
      gitFiles: [{ path: 'a.ts', status: 'modified', stage: 'unstaged', patch: PATCH_A }]
    })
    expect(entries).toHaveLength(1)
    expect(entries[0]?.filePath).toBe('a.ts')
  })

  it('still shows running edits while git is clean (edit racing the commit)', () => {
    const running = {
      ...fileChange('t1', 'a.ts', PATCH_A),
      status: 'running' as const
    }
    const entries = collectWorkspaceChangeEntries({
      blocks: [running],
      gitFiles: []
    })
    // A mid-flight edit must not vanish from the panel just because git
    // has not seen the write yet.
    expect(entries).toHaveLength(1)
  })
})
