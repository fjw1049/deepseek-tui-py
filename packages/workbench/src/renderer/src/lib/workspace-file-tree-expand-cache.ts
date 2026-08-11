/** Survives WorkspaceEditorPanel unmount when switching IDE center tabs. */

const expandedByRoot = new Map<string, string[]>()

export function readExpandedDirs(workspaceRoot: string): Set<string> {
  const key = workspaceRoot.trim()
  if (!key) return new Set([''])
  const stored = expandedByRoot.get(key)
  return stored ? new Set(stored) : new Set([''])
}

export function writeExpandedDirs(workspaceRoot: string, expanded: Set<string>): void {
  const key = workspaceRoot.trim()
  if (!key) return
  expandedByRoot.set(key, [...expanded])
}
