export type DiffStats = {
  added: number
  removed: number
}

function normalizePath(path: string): string {
  return path.replace(/\\/g, '/')
}

function trimTrailingSlash(path: string): string {
  return path.replace(/\/+$/, '')
}

export function looksLikeUnifiedDiff(text: string | undefined): boolean {
  if (!text) return false
  return text
    .split('\n')
    .some((line) => /^(@@|diff --git |--- |\+\+\+ |index )/.test(line))
}

export function extractDiffFilePath(
  patch: string | undefined,
  override?: string
): string | undefined {
  const preset = override?.trim()
  if (preset) return preset
  if (!patch) return undefined

  for (const line of patch.split('\n')) {
    if (line.startsWith('+++ ') || line.startsWith('--- ')) {
      const raw = line.slice(4).trim()
      const cleaned = raw.replace(/^[ab]\//, '')
      if (cleaned && cleaned !== '/dev/null') return cleaned
      continue
    }
    if (line.startsWith('diff --git ')) {
      const match = line.match(/ b\/(\S+)/)
      if (match?.[1]) return match[1]
    }
  }

  return undefined
}

export function formatFilePathForDisplay(
  filePath: string | undefined,
  workspaceRoot?: string
): string | undefined {
  const raw = filePath?.trim()
  if (!raw) return undefined

  const normalizedFilePath = normalizePath(raw)
  const normalizedWorkspaceRoot = trimTrailingSlash(normalizePath(workspaceRoot?.trim() ?? ''))
  if (!normalizedWorkspaceRoot) return normalizedFilePath

  const fileLower = normalizedFilePath.toLowerCase()
  const rootLower = normalizedWorkspaceRoot.toLowerCase()
  if (fileLower === rootLower) return normalizedFilePath
  if (!fileLower.startsWith(`${rootLower}/`)) return normalizedFilePath

  return normalizedFilePath.slice(normalizedWorkspaceRoot.length + 1)
}

/**
 * Count +/− like `git diff --numstat`: only hunk body lines.
 * File headers (`+++ b/file`) sit outside hunks and are ignored; a hunk line
 * whose content starts with `++` / `--` still counts.
 */
export function countDiffStats(patch: string | undefined): DiffStats | null {
  if (!patch) return null

  let added = 0
  let removed = 0
  let inHunk = false
  for (const line of patch.split('\n')) {
    if (line.startsWith('@@')) {
      inHunk = true
      continue
    }
    if (line.startsWith('diff --git ')) {
      inHunk = false
      continue
    }
    if (!inHunk) continue
    if (line.startsWith('+')) added += 1
    else if (line.startsWith('-')) removed += 1
  }

  if (added === 0 && removed === 0) return null
  return { added, removed }
}

/** Prefer runtime/ledger counts when present; otherwise parse the patch. */
export function resolvePatchStats(
  patch: string | undefined,
  explicit?: { added?: number; removed?: number } | null
): DiffStats | null {
  const added = explicit?.added
  const removed = explicit?.removed
  if (added !== undefined || removed !== undefined) {
    const stats = { added: Math.max(0, added ?? 0), removed: Math.max(0, removed ?? 0) }
    if (stats.added > 0 || stats.removed > 0) return stats
  }
  return countDiffStats(patch)
}

export function sumDiffStatsList(statsList: Array<DiffStats | null | undefined>): DiffStats | null {
  let added = 0
  let removed = 0
  let hasStats = false
  for (const stats of statsList) {
    if (!stats) continue
    added += stats.added
    removed += stats.removed
    hasStats = true
  }
  return hasStats ? { added, removed } : null
}

export function sumDiffStats(patches: Array<string | undefined>): DiffStats | null {
  return sumDiffStatsList(patches.map((patch) => countDiffStats(patch)))
}
