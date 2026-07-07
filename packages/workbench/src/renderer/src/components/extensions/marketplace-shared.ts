/**
 * Shared local-install helpers for the extension views (Skills / Connectors).
 * Extracted from the original PluginMarketplaceView so the two full-screen
 * pages reuse the exact same disk-write logic instead of duplicating it.
 */

export type NoticeTone = 'success' | 'error' | 'info'

export type Notice = {
  tone: NoticeTone
  message: string
}

/** Which on-disk artifact an extension item writes to. */
export type ExtensionKind = 'mcp' | 'skill'

const INSTALLED_STORAGE_KEY = 'deepseekgui.installedPlugins'

export function loadInstalledPlugins(): string[] {
  try {
    const raw = window.localStorage.getItem(INSTALLED_STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw) as unknown
    return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === 'string') : []
  } catch {
    return []
  }
}

export function saveInstalledPlugins(ids: string[]): void {
  try {
    window.localStorage.setItem(INSTALLED_STORAGE_KEY, JSON.stringify([...new Set(ids)]))
  } catch {
    /* localStorage may be unavailable */
  }
}

export function storageKey(kind: ExtensionKind, id: string): string {
  return `${kind}:${id}`
}

export function normalizePluginId(raw: string): string {
  return raw
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, '-')
    .replace(/^-+|-+$/g, '')
}

export function buildSkillContent(
  id: string,
  title: string,
  description: string,
  instructions: string
): string {
  return ['---', `name: ${id}`, `description: ${description}`, '---', '', `# ${title}`, '', instructions].join('\n')
}
