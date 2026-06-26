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

function migrateLegacyTab(): RightSidebarTab | null {
  try {
    const legacy = window.localStorage.getItem(LEGACY_PANEL_MODE_KEY)
    if (legacy === 'changes') return 'changes'
    if (legacy === 'browser') return 'preview'
    if (legacy === 'file') return 'editor'
  } catch {
    /* ignore */
  }
  return null
}

export function readStoredRightSidebarOpen(): boolean {
  const migrated = migrateLegacyTab()
  if (migrated) return true
  return readBoolean(OPEN_KEY, false)
}

export function persistRightSidebarOpen(open: boolean): void {
  persistBoolean(OPEN_KEY, open)
}

export function readStoredRightSidebarTab(): RightSidebarTab {
  const migrated = migrateLegacyTab()
  if (migrated) return migrated
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
