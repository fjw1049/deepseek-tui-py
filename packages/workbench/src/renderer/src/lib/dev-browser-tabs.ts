import { isLocalPreviewUrl } from '@shared/dev-preview-url'

export type PreviewTab = {
  id: string
  url: string | null
  title: string
}

export const PREVIEW_AUTO_FOLLOW_STORAGE_KEY = 'deepseekgui.devPreview.autoFollow'

/** Auto-follow defaults to off so chat-detected URLs never steal focus. */
export function resolveAutoFollow(stored: string | null): boolean {
  return stored === 'true'
}

export function createTab(url: string | null = null, title = ''): PreviewTab {
  return {
    id: `preview-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    url,
    title
  }
}

export function formatAddressInput(url: string | null): string {
  if (!url) return ''
  try {
    const parsed = new URL(url)
    const path = parsed.pathname === '/' ? '' : parsed.pathname
    return `${parsed.host}${path}${parsed.search}${parsed.hash}`
  } catch {
    return url
  }
}

export function tabLabel(tab: PreviewTab, fallback: string): string {
  if (tab.title.trim()) return tab.title.trim()
  if (!tab.url) return fallback
  try {
    const parsed = new URL(tab.url)
    const leaf = decodeURIComponent(parsed.pathname.split('/').filter(Boolean).at(-1) ?? '')
    return leaf || parsed.host || fallback
  } catch {
    return fallback
  }
}

export function updateTabById(
  tabs: PreviewTab[],
  tabId: string,
  patch: Partial<PreviewTab>
): PreviewTab[] {
  let changed = false
  const next = tabs.map((tab) => {
    if (tab.id !== tabId) return tab
    const merged = { ...tab, ...patch }
    // Webview events (did-navigate, page-title-updated) fire for URLs/titles
    // the state already holds; bail out referentially so they don't trigger
    // a re-render (and downstream effects) per event.
    if (merged.url === tab.url && merged.title === tab.title) return tab
    changed = true
    return merged
  })
  return changed ? next : tabs
}

export type OpenOrFocusOptions = {
  title?: string
  select?: boolean
}

export type TabState = {
  tabs: PreviewTab[]
  activeTabId: string
}

/**
 * Open `url` in the tab strip: focus an existing tab with the same URL, fill
 * the first blank tab, or append a new tab. Caller must normalize the URL.
 */
export function reduceOpenOrFocusUrl(
  state: TabState,
  url: string,
  options: OpenOrFocusOptions = {}
): TabState {
  const { tabs, activeTabId } = state
  const select = options.select !== false

  const existing = tabs.find((tab) => tab.url === url)
  if (existing) {
    return {
      tabs: options.title ? updateTabById(tabs, existing.id, { title: options.title }) : tabs,
      activeTabId: select ? existing.id : activeTabId
    }
  }

  // Prefer filling an existing blank tab (usually the initial one) so we
  // don't leave a stuck empty "first tab" beside the real preview.
  const emptyIndex = tabs.findIndex((tab) => !tab.url)
  if (emptyIndex >= 0) {
    const target = tabs[emptyIndex]!
    return {
      tabs: tabs.map((tab, index) =>
        index === emptyIndex ? { ...tab, url, title: options.title ?? '' } : tab
      ),
      activeTabId: select ? target.id : activeTabId
    }
  }

  const next = createTab(url, options.title ?? '')
  return {
    tabs: [...tabs, next],
    activeTabId: select ? next.id : activeTabId
  }
}

export type CloseTabResult = TabState & {
  /** True when the sole tab was cleared in place instead of removed. */
  clearedSoleTab: boolean
}

/**
 * Close a tab. The sole tab is cleared in place (never removed) so the strip
 * always keeps one tab; closing the active tab focuses the left neighbor.
 */
export function reduceCloseTab(state: TabState, tabId: string): CloseTabResult {
  const { tabs, activeTabId } = state
  const target = tabs.find((tab) => tab.id === tabId)
  if (!target) return { tabs, activeTabId, clearedSoleTab: false }

  if (tabs.length <= 1) {
    if (!target.url && !target.title) return { tabs, activeTabId, clearedSoleTab: false }
    return {
      tabs: [{ ...target, url: null, title: '' }],
      activeTabId,
      clearedSoleTab: true
    }
  }

  const index = tabs.findIndex((tab) => tab.id === tabId)
  const nextTabs = tabs.filter((tab) => tab.id !== tabId)
  if (tabId !== activeTabId) {
    return { tabs: nextTabs, activeTabId, clearedSoleTab: false }
  }
  const fallback = nextTabs[Math.max(0, index - 1)] ?? nextTabs[0]!
  return { tabs: nextTabs, activeTabId: fallback.id, clearedSoleTab: false }
}

export type DevBrowserView = 'empty' | 'webview' | 'iframe' | 'unsupported'

/** Pick the render path for the active tab's URL. */
export function selectDevBrowserView(
  activeUrl: string | null,
  useElectronWebview: boolean
): DevBrowserView {
  if (!activeUrl) return 'empty'
  if (useElectronWebview) return 'webview'
  return isLocalPreviewUrl(activeUrl) ? 'iframe' : 'unsupported'
}
