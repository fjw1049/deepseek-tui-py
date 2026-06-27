export type RightSidebarTab = 'editor' | 'changes' | 'terminal' | 'preview'

const OPEN_KEY = 'deepseekgui.layout.rightSidebarOpen'
const TAB_KEY = 'deepseekgui.layout.rightSidebarTab'
const COLLAPSED_KEY = 'deepseekgui.layout.rightSidebarCollapsed'
const LEGACY_PANEL_MODE_KEY = 'deepseekgui.layout.rightPanelMode'

const VALID_TABS = new Set<RightSidebarTab>(['editor', 'changes', 'terminal', 'preview'])

function readBoolean(key: string, fallback: boolean): boolean {
  try {
    const raw = window.localStorage.getItem(key)
    if (raw === 'true') return true
    if (raw === 'false') return false
  } catch {
    /* ignore */
  }
  return fallback
}

function persistBoolean(key: string, value: boolean): void {
  try {
    window.localStorage.setItem(key, String(value))
  } catch {
    /* ignore */
  }
}

function runLegacyMigrationOnce(): void {
  try {
    const legacy = window.localStorage.getItem(LEGACY_PANEL_MODE_KEY)
    if (legacy === null) return

    let tab: RightSidebarTab | null = null
    if (legacy === 'changes') tab = 'changes'
    else if (legacy === 'browser') tab = 'preview'
    else if (legacy === 'file') tab = 'editor'

    window.localStorage.removeItem(LEGACY_PANEL_MODE_KEY)

    if (!tab) return
    if (window.localStorage.getItem(TAB_KEY) === null) {
      window.localStorage.setItem(TAB_KEY, tab)
    }
    if (window.localStorage.getItem(OPEN_KEY) === null) {
      window.localStorage.setItem(OPEN_KEY, 'true')
    }
  } catch {
    /* ignore */
  }
}

runLegacyMigrationOnce()

export function readStoredRightSidebarOpen(): boolean {
  return readBoolean(OPEN_KEY, false)
}

export function persistRightSidebarOpen(open: boolean): void {
  persistBoolean(OPEN_KEY, open)
}

export function readStoredRightSidebarTab(): RightSidebarTab {
  try {
    const raw = window.localStorage.getItem(TAB_KEY)
    if (raw && VALID_TABS.has(raw as RightSidebarTab)) return raw as RightSidebarTab
  } catch {
    /* ignore */
  }
  return 'editor'
}

export function persistRightSidebarTab(tab: RightSidebarTab): void {
  try {
    window.localStorage.setItem(TAB_KEY, tab)
  } catch {
    /* ignore */
  }
}

export function readStoredRightSidebarCollapsed(): boolean {
  return readBoolean(COLLAPSED_KEY, false)
}

export function persistRightSidebarCollapsed(collapsed: boolean): void {
  persistBoolean(COLLAPSED_KEY, collapsed)
}
