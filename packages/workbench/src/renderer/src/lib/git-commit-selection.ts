function workspaceKey(path: string): string {
  return path.replace(/\\/g, '/').replace(/\/+$/, '').trim()
}

export { workspaceKey }

export function resolveGitCommitPaths(
  selectedPaths: string[],
  allPaths: string[],
  selectionKey: string | null,
  workspaceRoot: string
): string[] {
  if (allPaths.length === 0) return []
  const allowed = new Set(allPaths)
  const filtered = selectedPaths.filter((path) => allowed.has(path))
  if (filtered.length > 0) return filtered
  const key = workspaceKey(workspaceRoot)
  // Selection not initialized yet (e.g. before sync runs) — default to all git paths.
  if (selectedPaths.length === 0 && workspaceKey(selectionKey ?? '') !== key) {
    return [...allPaths]
  }
  return filtered
}

export function syncGitCommitSelection(
  previousKey: string | null,
  previousPaths: string[],
  workspaceRoot: string,
  allPaths: string[]
): { key: string | null; paths: string[] } {
  const key = workspaceKey(workspaceRoot)
  if (!key) {
    return { key: null, paths: [] }
  }
  const previous = workspaceKey(previousKey ?? '')
  if (allPaths.length === 0) {
    // Keep selection during transient empty snapshots (loading / reload).
    if (previous === key) {
      return { key, paths: previousPaths }
    }
    return { key: null, paths: [] }
  }
  if (previous !== key) {
    return { key, paths: [...allPaths] }
  }
  if (previousPaths.length === 0) {
    return { key, paths: [...allPaths] }
  }
  const previousSet = new Set(previousPaths)
  const kept = allPaths.filter((path) => previousSet.has(path))
  const added = allPaths.filter((path) => !previousSet.has(path))
  return { key, paths: [...kept, ...added] }
}

export function isExplicitGitCommitSelectionNone(
  selectionKey: string | null,
  selectedPaths: string[],
  allPaths: string[],
  workspaceRoot: string
): boolean {
  if (allPaths.length === 0) return false
  return (
    workspaceKey(selectionKey ?? '') === workspaceKey(workspaceRoot) && selectedPaths.length === 0
  )
}

export function toggleGitCommitPath(selectedPaths: string[], path: string, allPaths: string[]): string[] {
  const allowed = new Set(allPaths)
  if (!allowed.has(path)) return selectedPaths.filter((item) => item !== path)
  if (selectedPaths.includes(path)) {
    return selectedPaths.filter((item) => item !== path)
  }
  return [...selectedPaths, path]
}
