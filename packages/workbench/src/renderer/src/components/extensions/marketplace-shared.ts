/**
 * Shared local-install helpers for the marketplace panels (Skills / Connectors),
 * so both reuse the exact same disk-write logic instead of duplicating it.
 */

import { useEffect } from 'react'

export type NoticeTone = 'success' | 'error' | 'info'

export type Notice = {
  tone: NoticeTone
  message: string
  /** Instructions or unresolved conditions that need explicit dismissal. */
  persistent?: boolean
}

/** Success/info feedback is transient; failures remain until dismissed or resolved. */
export function useNoticeAutoDismiss(
  notice: Notice | null,
  setNotice: (value: Notice | null) => void
): void {
  useEffect(() => {
    if (!notice || notice.tone === 'error' || notice.persistent) return
    let timer: number | undefined
    const schedule = (): void => {
      window.clearTimeout(timer)
      if (document.visibilityState !== 'hidden') {
        timer = window.setTimeout(() => setNotice(null), 3000)
      }
    }
    schedule()
    document.addEventListener('visibilitychange', schedule)
    return () => {
      window.clearTimeout(timer)
      document.removeEventListener('visibilitychange', schedule)
    }
  }, [notice, setNotice])
}

/** Which on-disk artifact an extension item writes to. */
export type ExtensionKind = 'mcp' | 'skill'

const MARKETPLACE_KIND_KEY = 'deepseekgui.marketplace.kind'

export function loadMarketplaceKind(): 'mcp' | 'skills' | 'plugins' {
  try {
    if (typeof window === 'undefined') return 'mcp'
    const raw = window.localStorage.getItem(MARKETPLACE_KIND_KEY)
    if (raw === 'mcp' || raw === 'skills' || raw === 'plugins') return raw
  } catch {
    /* localStorage may be unavailable */
  }
  return 'mcp'
}

export type MarketplacePanelProps = {
  query: string
  createOpen: boolean
  onCreateClose: () => void
  createHost: HTMLElement | null
}

export function saveMarketplaceKind(kind: 'mcp' | 'skills' | 'plugins'): void {
  try {
    window.localStorage.setItem(MARKETPLACE_KIND_KEY, kind)
  } catch {
    /* localStorage may be unavailable */
  }
}

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
