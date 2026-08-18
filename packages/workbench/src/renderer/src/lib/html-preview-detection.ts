import type { ChatBlock, ToolBlock } from '../agent/types'
import { isHtmlPreviewPath } from '@shared/html-preview'
import { findFileReferences } from './file-references'

const MAX_DETECTED_HTML_PATHS = 4

/** Reject URL-shaped paths that web_search / fetch dumps into tool text. */
export function isRemoteUrlPath(path: string): boolean {
  const value = path.trim()
  if (!value) return false
  if (/^[a-z][a-z0-9+.-]*:\/\//i.test(value)) return true
  if (value.includes('://')) return true
  return false
}

function pushPath(paths: string[], seen: Set<string>, candidate: string): boolean {
  const value = candidate.trim()
  if (!value || isRemoteUrlPath(value) || !isHtmlPreviewPath(value) || seen.has(value)) {
    return false
  }
  seen.add(value)
  paths.push(value)
  return paths.length >= MAX_DETECTED_HTML_PATHS
}

/**
 * Detect local HTML artifacts for the Preview tab.
 *
 * Only trusts:
 * - `file_change` tools with an `.html` `filePath`
 * - assistant text mentioning a non-URL filesystem path
 *
 * Does **not** scan web_search / fetch_url tool dumps — those often contain
 * remote `https://…/*.html` links that are not workspace files.
 */
export function extractDetectedHtmlPreviewPaths(blocks: ChatBlock[]): string[] {
  const paths: string[] = []
  const seen = new Set<string>()

  for (let i = blocks.length - 1; i >= 0; i -= 1) {
    const block = blocks[i]!

    if (block.kind === 'tool') {
      if (block.toolKind === 'file_change' && block.filePath) {
        if (pushPath(paths, seen, block.filePath)) return paths
      }
      continue
    }

    if (block.kind !== 'assistant') continue
    for (const match of findFileReferences(block.text)) {
      if (pushPath(paths, seen, match.target.path)) return paths
    }
  }

  return paths
}

export function extractLatestTurnHtmlPreviewPaths(blocks: ChatBlock[]): string[] {
  let latestUserIndex = -1
  for (let i = blocks.length - 1; i >= 0; i -= 1) {
    if (blocks[i]?.kind === 'user') {
      latestUserIndex = i
      break
    }
  }
  if (latestUserIndex === -1) return []
  return extractDetectedHtmlPreviewPaths(blocks.slice(latestUserIndex + 1))
}

export function formatHtmlPreviewPathLabel(path: string): string {
  const normalized = path.replace(/\\/g, '/')
  const parts = normalized.split('/')
  return parts[parts.length - 1] || normalized
}

function basenameLower(path: string): string {
  const normalized = path.replace(/\\/g, '/')
  const parts = normalized.split('/')
  return (parts[parts.length - 1] || normalized).toLowerCase()
}

function isMarkdownPath(path: string): boolean {
  const base = basenameLower(path)
  return base.endsWith('.md') || base.endsWith('.mdx')
}

function markdownRank(path: string): number {
  const base = basenameLower(path)
  if (base.includes('report') || base.startsWith('research_')) return 2
  return 1
}

export type OpenableTurnResultKind = 'markdown' | 'html'

export type OpenableTurnResult = {
  path: string
  kind: OpenableTurnResultKind
}

const MAX_OPENABLE_TURN_RESULTS = 4

function resultRank(path: string, kind: OpenableTurnResultKind): number {
  if (kind === 'html') return 3
  return markdownRank(path)
}

function pathKey(path: string): string {
  return path.replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase()
}

/**
 * Openable artifacts from a turn's file_change list: `.md` / `.mdx` / `.html`.
 * Prefers HTML and report/research_* names; later writes win ties. Caps at 4.
 */
export function selectOpenableTurnResults(changes: ToolBlock[]): OpenableTurnResult[] {
  const latestByKey = new Map<
    string,
    { path: string; kind: OpenableTurnResultKind; rank: number; index: number }
  >()

  for (let i = 0; i < changes.length; i += 1) {
    const change = changes[i]!
    if (change.status === 'error') continue
    const path = change.filePath?.trim()
    if (!path || isRemoteUrlPath(path)) continue
    const kind: OpenableTurnResultKind | null = isHtmlPreviewPath(path)
      ? 'html'
      : isMarkdownPath(path)
        ? 'markdown'
        : null
    if (!kind) continue
    latestByKey.set(pathKey(path), {
      path,
      kind,
      rank: resultRank(path, kind),
      index: i
    })
  }

  return [...latestByKey.values()]
    .sort((a, b) => (b.rank !== a.rank ? b.rank - a.rank : b.index - a.index))
    .slice(0, MAX_OPENABLE_TURN_RESULTS)
    .map(({ path, kind }) => ({ path, kind }))
}

/**
 * Pick the primary Markdown write from a turn's file_change list.
 * Prefers report/research_* names; otherwise the last successful `.md` write.
 */
export function selectPrimaryMarkdownResult(changes: ToolBlock[]): ToolBlock | null {
  let best: ToolBlock | null = null
  let bestRank = -1
  let bestIndex = -1

  for (let i = 0; i < changes.length; i += 1) {
    const change = changes[i]!
    if (change.status === 'error') continue
    const path = change.filePath?.trim()
    if (!path || !isMarkdownPath(path)) continue
    const rank = markdownRank(path)
    // Later writes win ties so the final report beats an earlier plan.md.
    if (rank > bestRank || (rank === bestRank && i >= bestIndex)) {
      best = change
      bestRank = rank
      bestIndex = i
    }
  }

  return best
}
