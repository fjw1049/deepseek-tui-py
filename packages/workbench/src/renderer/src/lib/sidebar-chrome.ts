import { normalizeWorkspaceRoot } from './workspace-path'

export const SIDEBAR_LABEL_COLORS = [
  { id: 'red', swatch: '#ef4444' },
  { id: 'green', swatch: '#22c55e' },
  { id: 'yellow', swatch: '#eab308' },
  { id: 'purple', swatch: '#a78bfa' },
  { id: 'pink', swatch: '#f472b6' },
  { id: 'blue', swatch: '#38bdf8' }
] as const

export type SidebarLabelColorId = (typeof SIDEBAR_LABEL_COLORS)[number]['id']

export type SidebarLabelColor = SidebarLabelColorId | null

const HIDDEN_WORKSPACES_KEY = 'deepseekgui.hiddenWorkspaces'
const LABEL_COLORS_KEY = 'deepseekgui.sidebarLabelColors'
export const SIDEBAR_CHROME_CHANGED_EVENT = 'deepseekgui:sidebar-chrome-changed'

function normalizePathSeparators(path: string): string {
  return path.replace(/\\/g, '/').replace(/\/+$/, '')
}

function emitChromeChanged(): void {
  try {
    window.dispatchEvent(new Event(SIDEBAR_CHROME_CHANGED_EVENT))
  } catch {
    /* ignore */
  }
}

export function workspaceLabelKey(workspacePath: string): string {
  return `w:${normalizeWorkspaceRoot(workspacePath)}`
}

export function threadLabelKey(threadId: string): string {
  return `t:${threadId.trim()}`
}

export function loadHiddenWorkspacePaths(): string[] {
  try {
    const raw = localStorage.getItem(HIDDEN_WORKSPACES_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw) as unknown
    if (!Array.isArray(parsed)) return []
    return parsed
      .filter((item): item is string => typeof item === 'string' && item.trim().length > 0)
      .map((item) => normalizeWorkspaceRoot(item))
      .filter(Boolean)
  } catch {
    return []
  }
}

export function saveHiddenWorkspacePaths(paths: string[]): void {
  try {
    localStorage.setItem(HIDDEN_WORKSPACES_KEY, JSON.stringify(paths))
    emitChromeChanged()
  } catch {
    /* ignore */
  }
}

export function loadSidebarLabelColors(): Record<string, SidebarLabelColorId> {
  try {
    const raw = localStorage.getItem(LABEL_COLORS_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw) as unknown
    if (!parsed || typeof parsed !== 'object') return {}
    const valid = new Set<string>(SIDEBAR_LABEL_COLORS.map((c) => c.id))
    const next: Record<string, SidebarLabelColorId> = {}
    for (const [key, value] of Object.entries(parsed as Record<string, unknown>)) {
      if (typeof key !== 'string' || !key || typeof value !== 'string') continue
      if (!valid.has(value)) continue
      next[key] = value as SidebarLabelColorId
    }
    return next
  } catch {
    return {}
  }
}

export function saveSidebarLabelColors(map: Record<string, SidebarLabelColorId>): void {
  try {
    localStorage.setItem(LABEL_COLORS_KEY, JSON.stringify(map))
    emitChromeChanged()
  } catch {
    /* ignore */
  }
}

export function sidebarLabelSwatch(color: SidebarLabelColor): string | null {
  if (!color) return null
  return SIDEBAR_LABEL_COLORS.find((item) => item.id === color)?.swatch ?? null
}

/** Path relative to project root; `.` when equal. Falls back to absolute when outside. */
export function toProjectRelativePath(absolutePath: string, projectRoot: string): string {
  const abs = normalizePathSeparators(absolutePath.trim())
  const root = normalizePathSeparators(projectRoot.trim())
  if (!abs) return ''
  if (!root) return abs
  if (abs === root) return '.'
  const absLower = abs.toLowerCase()
  const rootLower = root.toLowerCase()
  if (absLower.startsWith(`${rootLower}/`)) {
    return abs.slice(root.length + 1)
  }
  return abs
}

/** Prefer project-relative; when the target *is* the project root, use home-relative. */
export function copyableRelativePath(absolutePath: string, projectRoot: string): string {
  const abs = normalizePathSeparators(absolutePath.trim())
  const root = normalizePathSeparators(projectRoot.trim())
  if (!abs) return ''
  if (root && abs === root) return toHomeRelativePath(abs)
  if (root) {
    const relative = toProjectRelativePath(abs, root)
    if (relative !== abs) return relative
  }
  return toHomeRelativePath(abs)
}

export function toHomeRelativePath(absolutePath: string): string {
  const abs = normalizePathSeparators(absolutePath.trim())
  if (!abs) return ''
  const match = abs.match(/^(\/Users\/[^/]+|\/home\/[^/]+|\/private\/var\/[^/]+|[A-Za-z]:\/Users\/[^/]+)/i)
  if (!match) return abs
  const home = match[1]
  if (abs.length === home.length) return '~'
  if (abs.toLowerCase().startsWith(`${home.toLowerCase()}/`)) {
    return `~/${abs.slice(home.length + 1)}`
  }
  return abs
}

export function isWorkspaceHidden(
  workspacePath: string,
  hiddenPaths: ReadonlyArray<string>
): boolean {
  const normalized = normalizeWorkspaceRoot(workspacePath)
  if (!normalized) return false
  const target = normalized.toLowerCase()
  return hiddenPaths.some((path) => normalizeWorkspaceRoot(path).toLowerCase() === target)
}
