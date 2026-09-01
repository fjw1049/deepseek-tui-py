/** Derive Edited rows / turn summary from file_change blocks + turn.diff snapshots. */

import type { ChatBlock, ToolBlock } from '../agent/types'
import {
  looksLikeUnifiedDiff,
  extractDiffFilePath,
  resolvePatchStats,
  type DiffStats
} from './diff-stats'

export type TurnDiffFile = {
  path: string
  op?: string
  additions: number
  deletions: number
  unified_diff: string
  detail_truncated?: boolean
}

export type TurnDiffSnapshot = {
  turn_id: string
  files: TurnDiffFile[]
  totals: { files: number; additions: number; deletions: number }
  revision: number
  merged_unified_diff?: string
  complete: boolean
}

export type EditedRow = {
  id: string
  path: string
  additions: number
  deletions: number
  status: 'running' | 'success' | 'error'
  detail?: string
  agentId?: string
}

export function isFileChangeToolBlock(block: ChatBlock): block is ToolBlock {
  return block.kind === 'tool' && block.toolKind === 'file_change'
}

/** Per-tool Edited rows from lifecycle file_change items (legacy + live). */
export function editedRowsFromToolBlocks(blocks: ChatBlock[]): EditedRow[] {
  const rows: EditedRow[] = []
  for (const block of blocks) {
    if (!isFileChangeToolBlock(block)) continue
    const detail = block.detail?.trim() ?? ''
    const path =
      formatPath(block.filePath) ||
      (looksLikeUnifiedDiff(detail) ? extractDiffFilePath(detail, block.filePath) : undefined) ||
      ''
    if (!path && !looksLikeUnifiedDiff(detail)) continue
    const mutation =
      block.meta?.mutation &&
      typeof block.meta.mutation === 'object' &&
      !Array.isArray(block.meta.mutation)
        ? (block.meta.mutation as Record<string, unknown>)
        : undefined
    const stats = resolvePatchStats(looksLikeUnifiedDiff(detail) ? detail : undefined, {
      added: typeof mutation?.additions === 'number' ? mutation.additions : undefined,
      removed: typeof mutation?.deletions === 'number' ? mutation.deletions : undefined
    })
    rows.push({
      id: block.id,
      path: path || 'file',
      additions: stats?.added ?? 0,
      deletions: stats?.removed ?? 0,
      status: block.status,
      detail: looksLikeUnifiedDiff(detail) ? detail : undefined,
      agentId:
        typeof block.meta?.agent_id === 'string'
          ? block.meta.agent_id
          : typeof block.meta?.mutation === 'object' &&
              block.meta.mutation !== null &&
              typeof (block.meta.mutation as { agent_id?: unknown }).agent_id === 'string'
            ? (block.meta.mutation as { agent_id: string }).agent_id
            : undefined
    })
  }
  return rows
}

/**
 * Resolve which turn-diff snapshot to show for the latest timeline turn.
 * While busy: currentTurnId. After complete: lastCompletedTurnId (snapshots
 * are retained in turnDiffByTurnId; currentTurnId is cleared on complete).
 */
export function resolveLatestTurnDiffId(
  currentTurnId: string | null | undefined,
  lastCompletedTurnId: string | null | undefined
): string | null {
  return currentTurnId || lastCompletedTurnId || null
}

/** Bind a timeline turn to its own durable snapshot; latest-id fallback is legacy only. */
export function resolveTurnDiffId(
  turnId: string | null | undefined,
  isLatestTurn: boolean,
  currentTurnId: string | null | undefined,
  lastCompletedTurnId: string | null | undefined
): string | null {
  return turnId || (isLatestTurn ? resolveLatestTurnDiffId(currentTurnId, lastCompletedTurnId) : null)
}

export function statsForTurnFile(file: TurnDiffFile): DiffStats {
  return (
    resolvePatchStats(file.unified_diff, {
      added: file.additions,
      removed: file.deletions
    }) ?? { added: 0, removed: 0 }
  )
}

export function totalsFromTurnFiles(
  files: TurnDiffFile[]
): { files: number; additions: number; deletions: number } {
  let additions = 0
  let deletions = 0
  for (const file of files) {
    const stats = statsForTurnFile(file)
    additions += stats.added
    deletions += stats.removed
  }
  return { files: files.length, additions, deletions }
}

/** Folded turn summary — prefer turn.diff.updated snapshot; fall back to tool blocks. */
export function turnSummaryFromSources(
  snapshot: TurnDiffSnapshot | null | undefined,
  blocks: ChatBlock[]
): { files: TurnDiffFile[]; totals: { files: number; additions: number; deletions: number } } {
  if (snapshot) {
    const files = snapshot.files.map((f) => ({
      path: f.path,
      op: f.op,
      additions: f.additions ?? 0,
      deletions: f.deletions ?? 0,
      unified_diff: f.unified_diff ?? '',
      detail_truncated: f.detail_truncated
    }))
    return { files, totals: totalsFromTurnFiles(files) }
  }
  const byPath = new Map<string, TurnDiffFile>()
  for (const row of editedRowsFromToolBlocks(blocks)) {
    if (row.status === 'error') continue
    const path = row.path.replace(/\\/g, '/').trim()
    if (!path) continue
    byPath.set(path.toLowerCase(), {
      path: row.path,
      additions: row.additions,
      deletions: row.deletions,
      unified_diff: row.detail ?? ''
    })
  }
  const files = [...byPath.values()]
  return { files, totals: totalsFromTurnFiles(files) }
}

/** ToolBlock[] for TurnChangeSummary / ChangeInspector from a turn summary. */
export function toolBlocksFromTurnSummary(
  turnId: string,
  summary: ReturnType<typeof turnSummaryFromSources>
): ToolBlock[] {
  return summary.files.map((f, index) => {
    const stats = statsForTurnFile(f)
    return {
      kind: 'tool' as const,
      id: `turn-diff:${turnId}:${f.path}:${index}`,
      summary: `edit_file: path="${f.path}"`,
      status: 'success' as const,
      toolKind: 'file_change' as const,
      detail: f.unified_diff,
      filePath: f.path,
      meta: {
        mutation: {
          additions: stats.added,
          deletions: stats.removed
        }
      }
    }
  })
}

function formatPath(path: string | undefined): string {
  return (path ?? '').replace(/\\/g, '/').trim()
}

export function parseTurnDiffPayload(payload: unknown): TurnDiffSnapshot | null {
  if (!payload || typeof payload !== 'object') return null
  const p = payload as Record<string, unknown>
  const turnId = typeof p.turn_id === 'string' ? p.turn_id : ''
  if (!turnId) return null
  const filesRaw = Array.isArray(p.files) ? p.files : []
  const files: TurnDiffFile[] = []
  for (const entry of filesRaw) {
    if (!entry || typeof entry !== 'object') continue
    const f = entry as Record<string, unknown>
    const path = typeof f.path === 'string' ? f.path : ''
    if (!path) continue
    files.push({
      path,
      op: typeof f.op === 'string' ? f.op : undefined,
      additions: typeof f.additions === 'number' ? f.additions : 0,
      deletions: typeof f.deletions === 'number' ? f.deletions : 0,
      unified_diff: typeof f.unified_diff === 'string' ? f.unified_diff : '',
      detail_truncated: Boolean(f.detail_truncated)
    })
  }
  const totalsRaw =
    p.totals && typeof p.totals === 'object' ? (p.totals as Record<string, unknown>) : {}
  return {
    turn_id: turnId,
    files,
    totals: {
      files: typeof totalsRaw.files === 'number' ? totalsRaw.files : files.length,
      additions: typeof totalsRaw.additions === 'number' ? totalsRaw.additions : 0,
      deletions: typeof totalsRaw.deletions === 'number' ? totalsRaw.deletions : 0
    },
    revision: typeof p.revision === 'number' ? p.revision : 0,
    merged_unified_diff:
      typeof p.merged_unified_diff === 'string' ? p.merged_unified_diff : undefined,
    complete: Boolean(p.complete)
  }
}

export function indexTurnDiffSnapshots(payloads: unknown[]): Record<string, TurnDiffSnapshot> {
  const byTurnId: Record<string, TurnDiffSnapshot> = {}
  for (const payload of payloads) {
    const snapshot = parseTurnDiffPayload(payload)
    if (snapshot) byTurnId[snapshot.turn_id] = snapshot
  }
  return byTurnId
}
