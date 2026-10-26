import { create } from 'zustand'

/** One tab of the Workbench browser; pages live in the always-mounted page layer. */
export type PageTab = {
  id: string
  url: string
  title: string
  /** Workspace HTML source opened in this tab; enables element picking. */
  filePath: string | null
  loading: boolean
  error: string | null
}
export type PageRect = { top: number; left: number; width: number; height: number }
export type PageSession = {
  tabs: PageTab[]; activeTabId: string; retained?: boolean; inputBlocked?: boolean
  /** While set, only this tab (the one the agent drives) is blocked; other tabs stay usable. */
  blockedTabId?: string | null
}

/** Input stays blocked until a browser panel says otherwise. */
export function tabInputBlocked(session: PageSession, tabId: string): boolean {
  return (session.inputBlocked ?? true) && (!session.blockedTabId || session.blockedTabId === tabId)
}

export type PageWebview = HTMLElement & {
  canGoBack(): boolean
  canGoForward(): boolean
  getURL(): string
  getWebContentsId(): number
  goBack(): void
  goForward(): void
  loadURL(url: string): Promise<void>
  openDevTools(): void
  reloadIgnoringCache(): void
  stop(): void
  setAudioMuted(muted: boolean): void
  executeJavaScript(code: string): Promise<unknown>
}

type State = {
  sessions: Record<string, PageSession>
  /** The sidebar page area showing a browser, relative to the page layer. */
  display: { browserId: string; rect: PageRect } | null
}

export const BLANK_PAGE = 'about:blank'
/** Conversations whose pages stay open; matches the runtime's own session limit. */
export const MAX_BROWSER_SESSIONS = 8
/** A browser used this recently may be in the middle of an agent task; it stays. */
const RECENT_USE_MS = 10 * 60 * 1000
export const useBrowserPagesStore = create<State>(() => ({ sessions: {}, display: null }))

const lastUsed = new Map<string, number>()
/** Opening, switching or showing a browser is use; page events inside it are not. */
const touch = (browserId: string): void => { lastUsed.set(browserId, Date.now()) }

/** Pages of reclaimed browsers, reopened by URL when their conversation shows the browser again. */
const dormant = new Map<string, { tabs: PageTab[]; activeIndex: number }>()

const webviews = new Map<string, PageWebview>()
/** Tabs whose page finished attaching; only those accept loadURL. */
const readyTabs = new Set<string>()

export function markPageReady(tabId: string, ready: boolean): void {
  if (ready) readyTabs.add(tabId)
  else readyTabs.delete(tabId)
}

export function pageWebview(tabId: string | undefined): PageWebview | null {
  return (tabId && webviews.get(tabId)) || null
}

export function registerPageWebview(tabId: string, webview: PageWebview | null): void {
  if (webview) webviews.set(tabId, webview)
  else webviews.delete(tabId)
}

function createPageTab(url: string, filePath: string | null): PageTab {
  return { id: crypto.randomUUID(), url, title: '', filePath, loading: url !== BLANK_PAGE, error: null }
}

function setSession(browserId: string, session: PageSession): void {
  useBrowserPagesStore.setState(state => ({ sessions: { ...state.sessions, [browserId]: session } }))
}

const isBlank = (session: PageSession): boolean =>
  session.tabs.every(tab => tab.url === BLANK_PAGE && !tab.title && !tab.loading)

/**
 * Close browsers beyond the limit, never the one on screen: blank ones first, then the
 * least recently used. A closed browser's URLs reopen later; unsaved page state does not.
 */
function prune(): void {
  const { sessions, display } = useBrowserPagesStore.getState()
  const idle = Object.keys(sessions)
    .filter(id => !sessions[id]?.retained && id !== display?.browserId && Date.now() - (lastUsed.get(id) ?? 0) >= RECENT_USE_MS)
    .sort((a, b) => Number(isBlank(sessions[b]!)) - Number(isBlank(sessions[a]!)) ||
      (lastUsed.get(a) ?? 0) - (lastUsed.get(b) ?? 0))
  const excess = Object.keys(sessions).length - MAX_BROWSER_SESSIONS
  if (excess <= 0) return
  const closing = new Set(idle.slice(0, excess))
  for (const id of closing) {
    lastUsed.delete(id)
    const session = sessions[id]!
    if (!isBlank(session)) {
      dormant.set(id, { tabs: session.tabs, activeIndex: session.tabs.findIndex(tab => tab.id === session.activeTabId) })
    }
  }
  useBrowserPagesStore.setState(state => ({
    sessions: Object.fromEntries(Object.entries(state.sessions).filter(([id]) => !closing.has(id)))
  }))
}

/** Also protects separate popup windows managed by the main process. */
export function setBrowserInputBlocked(browserId: string, inputBlocked: boolean, blockedTabId: string | null = null): void {
  const session = useBrowserPagesStore.getState().sessions[browserId]
  if (session && (session.inputBlocked !== inputBlocked || (session.blockedTabId ?? null) !== blockedTabId)) {
    setSession(browserId, { ...session, inputBlocked, blockedTabId })
  }
}

/** A live runtime or recorder connection owns the page even when no panel shows it. */
export function retainBrowserSession(browserId: string, retained: boolean): boolean {
  const session = useBrowserPagesStore.getState().sessions[browserId]
  if (!session) return false
  setSession(browserId, { ...session, retained })
  return true
}

/** Every browser keeps at least one tab, so the runtime always has a page to drive. */
export function ensureBrowserSession(browserId: string): PageSession {
  const existing = useBrowserPagesStore.getState().sessions[browserId]
  touch(browserId)
  if (existing) return existing
  const saved = dormant.get(browserId)
  dormant.delete(browserId)
  const tabs = saved ? saved.tabs.map(tab => ({ ...createPageTab(tab.url, tab.filePath), title: tab.title }))
    : [createPageTab(BLANK_PAGE, null)]
  const session = { tabs, activeTabId: tabs[Math.max(0, saved?.activeIndex ?? 0)]!.id }
  setSession(browserId, session)
  prune()
  return session
}

export function openPageTab(browserId: string, url: string,
  { filePath = null, background = false }: { filePath?: string | null; background?: boolean } = {}): string {
  const session = ensureBrowserSession(browserId)
  const tab = createPageTab(url, filePath)
  setSession(browserId, { ...session, tabs: [...session.tabs, tab], activeTabId: background ? session.activeTabId : tab.id })
  return tab.id
}

export function activatePageTab(browserId: string, tabId: string): boolean {
  const session = useBrowserPagesStore.getState().sessions[browserId]
  if (!session?.tabs.some(tab => tab.id === tabId)) return false
  touch(browserId)
  if (session.activeTabId !== tabId) setSession(browserId, { ...session, activeTabId: tabId })
  return true
}

export function closePageTab(browserId: string, tabId: string, source: 'user' | 'runtime' = 'user'): boolean {
  const session = useBrowserPagesStore.getState().sessions[browserId]
  const index = session?.tabs.findIndex(tab => tab.id === tabId) ?? -1
  if (!session || index < 0) return false
  if (source === 'user' && tabInputBlocked(session, tabId)) return false
  const tabs = session.tabs.filter(tab => tab.id !== tabId)
  if (!tabs.length) tabs.push(createPageTab(BLANK_PAGE, null))
  const activeTabId = session.activeTabId === tabId ? tabs[Math.min(index, tabs.length - 1)]!.id : session.activeTabId
  setSession(browserId, { ...session, tabs, activeTabId })
  return true
}

/**
 * Load a page in a tab. A tab still attaching cannot load yet and would report its
 * first blank navigation afterwards, so it is replaced by a tab that starts there.
 */
export function navigatePageTab(browserId: string, tabId: string, url: string, filePath: string | null = null): void {
  const webview = webviews.get(tabId)
  if (webview && readyTabs.has(tabId)) {
    updatePageTab(browserId, tabId, { url, filePath, error: null })
    void webview.loadURL(url).catch(() => { /* Reported by the tab. */ })
    return
  }
  const session = useBrowserPagesStore.getState().sessions[browserId]
  if (!session?.tabs.some(tab => tab.id === tabId)) return
  const tab = createPageTab(url, filePath)
  setSession(browserId, {
    ...session,
    tabs: session.tabs.map(item => item.id === tabId ? tab : item),
    activeTabId: session.activeTabId === tabId ? tab.id : session.activeTabId
  })
}

export function updatePageTab(browserId: string, tabId: string, patch: Partial<PageTab>): void {
  const session = useBrowserPagesStore.getState().sessions[browserId]
  if (!session?.tabs.some(tab => tab.id === tabId)) return
  setSession(browserId, { ...session, tabs: session.tabs.map(tab => tab.id === tabId ? { ...tab, ...patch } : tab) })
}

export function setPageDisplay(display: State['display']): void {
  const current = useBrowserPagesStore.getState().display
  if (display) touch(display.browserId)
  if (display && current && current.browserId === display.browserId &&
    (['top', 'left', 'width', 'height'] as const).every(key => current.rect[key] === display.rect[key])) return
  if (!display && !current) return
  useBrowserPagesStore.setState({ display })
}
