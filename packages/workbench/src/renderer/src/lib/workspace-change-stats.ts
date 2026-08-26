/** One workspace-change list + one +/- total for inspector, dock, sidebar, and live fold-up. */

import type { GitWorkingChangeFile, GitWorkingChangeStage } from '@shared/git-working-changes'
import type { ChatBlock } from '../agent/types'
import {
  countDiffStats,
  extractDiffFilePath,
  looksLikeUnifiedDiff,
  resolvePatchStats,
  sumDiffStatsList,
  type DiffStats
} from './diff-stats'
import { firstChangedEditorLineFromPatch } from './parse-unified-diff-for-editor'
import type { TurnDiffFile, TurnDiffSnapshot } from './turn-mutation-view'
import { totalsFromTurnFiles } from './turn-mutation-view'
import { normalizeChangePath } from './workspace-change-path'

export type WorkspaceChangeEntry = {
  id: string
  filePath?: string
  detail: string
  status: 'running' | 'success' | 'error'
  editLine?: number
  committable?: boolean
  gitStage?: GitWorkingChangeStage
  additions?: number
  deletions?: number
}

function editLineFromDetail(
  detail: string,
  meta?: Record<string, unknown>
): number | undefined {
  const mutation =
    meta?.mutation && typeof meta.mutation === 'object' && !Array.isArray(meta.mutation)
      ? (meta.mutation as Record<string, unknown>)
      : undefined
  const fromMeta = mutation?.line_start
  if (typeof fromMeta === 'number' && Number.isFinite(fromMeta) && fromMeta >= 1) {
    return Math.floor(fromMeta)
  }
  return firstChangedEditorLineFromPatch(detail)
}

function upsert(
  byPath: Map<string, WorkspaceChangeEntry>,
  entry: WorkspaceChangeEntry
): void {
  const key = normalizeChangePath(entry.filePath) || entry.id
  byPath.set(key, entry)
}

/**
 * Unique current-workspace files, last write wins, git patch preferred
 * (vs HEAD) except while a session edit is still running.
 */
export function collectWorkspaceChangeEntries(opts: {
  blocks: ChatBlock[]
  turnDiffByTurnId?: Record<string, TurnDiffSnapshot>
  gitFiles?: GitWorkingChangeFile[] | null
}): WorkspaceChangeEntry[] {
  const byPath = new Map<string, WorkspaceChangeEntry>()
  // Paths git no longer reports dirty were committed (or reverted) since
  // the session blocks / turn snapshots were recorded. They are history,
  // not pending changes - keep them out of the inspector and its totals,
  // otherwise the panel keeps listing "changes" after every commit.
  // Only meaningful once the first git snapshot has loaded (null/undefined =
  // still loading / not a repo: fall back to showing session-sourced entries).
  const gitDirtyPaths =
    opts.gitFiles == null ? null : new Set(opts.gitFiles.map((file) => normalizeChangePath(file.path)))

  for (const block of opts.blocks) {
    if (!(block.kind === 'tool' && block.toolKind === 'file_change')) continue
    const detailText = block.detail?.trim() ?? ''
    const hasDiff = looksLikeUnifiedDiff(detailText)
    const filePath = extractDiffFilePath(detailText, block.filePath)
    if (!hasDiff && !filePath) continue
    // A settled (non-running) session edit whose path git no longer reports
    // dirty was committed/reverted since - drop it. Running edits always
    // show: git has not seen the write yet.
    if (
      block.status !== 'running' &&
      gitDirtyPaths !== null &&
      !gitDirtyPaths.has(normalizeChangePath(filePath))
    ) {
      continue
    }
    const mutation =
      block.meta?.mutation &&
      typeof block.meta.mutation === 'object' &&
      !Array.isArray(block.meta.mutation)
        ? (block.meta.mutation as Record<string, unknown>)
        : undefined
    upsert(byPath, {
      id: block.id,
      filePath,
      detail: hasDiff ? detailText : '',
      status: block.status,
      editLine: editLineFromDetail(detailText, block.meta),
      additions: typeof mutation?.additions === 'number' ? mutation.additions : undefined,
      deletions: typeof mutation?.deletions === 'number' ? mutation.deletions : undefined
    })
  }

  for (const snap of Object.values(opts.turnDiffByTurnId ?? {})) {
    for (const file of snap.files ?? []) {
      const detail = file.unified_diff?.trim() ?? ''
      const hasDiff = looksLikeUnifiedDiff(detail)
      const filePath = file.path?.trim() ?? ''
      if (!hasDiff && !filePath) continue
      if (
        gitDirtyPaths !== null &&
        filePath &&
        !gitDirtyPaths.has(normalizeChangePath(filePath))
      ) {
        continue
      }
      const key = normalizeChangePath(filePath) || `turn-ledger:${snap.turn_id}:${file.path}`
      const prev = byPath.get(key)
      if (prev?.status === 'running') continue
      upsert(byPath, {
        id: `turn-ledger:${snap.turn_id}:${file.path}`,
        filePath: filePath || extractDiffFilePath(detail),
        detail: hasDiff ? detail : prev?.detail ?? '',
        status: 'success',
        editLine: firstChangedEditorLineFromPatch(detail) ?? prev?.editLine,
        additions: file.additions,
        deletions: file.deletions
      })
    }
  }

  for (const file of opts.gitFiles ?? []) {
    const key = normalizeChangePath(file.path)
    if (!key) continue
    const prev = byPath.get(key)
    if (prev?.status === 'running' && (prev.detail ?? '').trim()) {
      byPath.set(key, { ...prev, committable: true, gitStage: file.stage })
      continue
    }
    const patch = file.patch?.trim() ?? ''
    const gitStats = countDiffStats(patch)
    upsert(byPath, {
      id: prev?.id ?? `git:${file.path}`,
      filePath: file.path,
      detail: patch || prev?.detail || '',
      status: prev?.status ?? 'success',
      editLine: firstChangedEditorLineFromPatch(patch) ?? prev?.editLine,
      committable: true,
      gitStage: file.stage,
      // Git vs HEAD is the working-tree truth. Drop last-edit ledger counts
      // so the header +/- matches the patch the list actually renders.
      additions: gitStats?.added ?? (patch ? undefined : prev?.additions),
      deletions: gitStats?.removed ?? (patch ? undefined : prev?.deletions)
    })
  }

  return [...byPath.values()]
}

export function workspaceChangeEntryStats(entry: WorkspaceChangeEntry): DiffStats | null {
  return resolvePatchStats(entry.detail, {
    added: entry.additions,
    removed: entry.deletions
  })
}

/**
 * Composer live strip: only this running turn's writes.
 * Do not fold in leftover git dirt or earlier turns — those belong in the
 * Changes panel, not "I just hit send and files already changed".
 */
export function collectLiveTurnChangeEntries(opts: {
  currentTurnId: string | null | undefined
  blocks: ChatBlock[]
  turnDiffByTurnId?: Record<string, TurnDiffSnapshot>
}): WorkspaceChangeEntry[] {
  const turnId = opts.currentTurnId?.trim()
  if (!turnId) return []
  const snap = opts.turnDiffByTurnId?.[turnId]
  const runningThisTurn = opts.blocks.filter(
    (block) =>
      block.kind === 'tool' &&
      block.toolKind === 'file_change' &&
      block.status === 'running'
  )
  return collectWorkspaceChangeEntries({
    blocks: runningThisTurn,
    turnDiffByTurnId: snap ? { [turnId]: snap } : {},
    gitFiles: null
  })
}

/** Header +/- must be the sum of the same per-file stats the list shows. */
export function sumWorkspaceChangeStats(entries: WorkspaceChangeEntry[]): DiffStats | null {
  return sumDiffStatsList(entries.map((entry) => workspaceChangeEntryStats(entry)))
}

/** Latest-turn fold-up uses the same files + +/- as the inspector. */
export function turnSummaryFromWorkspaceEntries(entries: WorkspaceChangeEntry[]): {
  files: TurnDiffFile[]
  totals: { files: number; additions: number; deletions: number }
} {
  const files: TurnDiffFile[] = []
  for (const entry of entries) {
    const path = entry.filePath?.trim()
    if (!path) continue
    const stats = workspaceChangeEntryStats(entry)
    files.push({
      path,
      additions: stats?.added ?? 0,
      deletions: stats?.removed ?? 0,
      unified_diff: entry.detail
    })
  }
  return { files, totals: totalsFromTurnFiles(files) }
}

export function workspaceChangePatchMap(
  entries: WorkspaceChangeEntry[]
): Map<string, string> {
  const map = new Map<string, string>()
  for (const entry of entries) {
    const key = normalizeChangePath(entry.filePath)
    const detail = entry.detail.trim()
    if (!key || !detail) continue
    map.set(key, detail)
  }
  return map
}
