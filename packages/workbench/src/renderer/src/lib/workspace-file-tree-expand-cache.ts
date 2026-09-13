/** Survives WorkspaceEditorPanel unmount and app restarts (localStorage-backed). */

const STORAGE_PREFIX = 'deepseekgui.layout.expandedDirs:'

const expandedByRoot = new Map<string, string[]>()

function storageKey(workspaceRoot: string): string {
  return STORAGE_PREFIX + workspaceRoot.trim()
}

export function readExpandedDirs(workspaceRoot: string): Set<string> {
  const key = workspaceRoot.trim()
  if (!key) return new Set([''])

  const memo = expandedByRoot.get(key)
  if (memo) return new Set(memo)

  try {
    const raw = window.localStorage.getItem(storageKey(key))
    if (raw) {
      const parsed: unknown = JSON.parse(raw)
      if (Array.isArray(parsed)) {
        const stored = parsed.filter((entry): entry is string => typeof entry === 'string')
        expandedByRoot.set(key, stored)
        return new Set(stored)
      }
    }
  } catch {
    /* corrupted or unavailable storage — fall through to the default */
  }
  return new Set([''])
}

export function writeExpandedDirs(workspaceRoot: string, expanded: Set<string>): void {
  const key = workspaceRoot.trim()
  if (!key) return
  const list = [...expanded]
  expandedByRoot.set(key, list)
  try {
    window.localStorage.setItem(storageKey(key), JSON.stringify(list))
  } catch {
    /* ignore */
  }
}
