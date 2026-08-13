import { describe, expect, it } from 'vitest'
import type { ChatBlock } from '../agent/types'
import {
  collectWorkspaceChangeEntries,
  sumWorkspaceChangeStats,
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
      gitFiles: [{ path: 'b.ts', status: 'added', stage: 'unstaged', patch: PATCH_B }]
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
  })
})
