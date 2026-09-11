export type RightSidebarTab = 'editor' | 'changes' | 'terminal' | 'preview' | 'runs'

const OPEN_KEY = 'deepseekgui.layout.rightSidebarOpen'
const PANELS_KEY = 'deepseekgui.layout.rightSidebarPanels'
const COLLAPSED_KEY = 'deepseekgui.layout.rightSidebarCollapsed'
const VALID_TABS = new Set<RightSidebarTab>(['editor', 'changes', 'terminal', 'preview'])

export type RightSidebarPanels = {
  tabs: RightSidebarTab[]
  activeTab: RightSidebarTab | null
}

export function addRightSidebarTab(state: RightSidebarPanels, tab: RightSidebarTab): RightSidebarPanels {
  return {
    tabs: state.tabs.includes(tab) ? state.tabs : [...state.tabs, tab],
    activeTab: tab
  }
}

export function removeRightSidebarTab(state: RightSidebarPanels, tab: RightSidebarTab): RightSidebarPanels {
  const index = state.tabs.indexOf(tab)
  if (index < 0) return state
  const tabs = state.tabs.filter((item) => item !== tab)
  return {
    tabs,
    activeTab: state.activeTab === tab ? tabs[Math.min(index, tabs.length - 1)] ?? null : state.activeTab
  }
}

export function readStoredRightSidebarPanels(): RightSidebarPanels {
  try {
    const stored = JSON.parse(window.localStorage.getItem(PANELS_KEY) ?? 'null')
    if (Array.isArray(stored?.tabs)) {
      const tabs = [...new Set<RightSidebarTab>(stored.tabs.filter((tab: RightSidebarTab) => VALID_TABS.has(tab)))]
      return { tabs, activeTab: tabs.includes(stored.activeTab) ? stored.activeTab : tabs[0] ?? null }
    }
  } catch {
    /* ignore */
  }
  return { tabs: [], activeTab: null }
}

export function persistRightSidebarPanels(state: RightSidebarPanels): void {
  try {
    // Run selection belongs to a live thread and must not be restored on launch.
    const tabs = state.tabs.filter((tab) => VALID_TABS.has(tab))
    window.localStorage.setItem(PANELS_KEY, JSON.stringify({
      tabs,
      activeTab: state.activeTab && tabs.includes(state.activeTab) ? state.activeTab : tabs[0] ?? null
    }))
  } catch {
    /* ignore */
  }
}

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

/** Last open flag — Workbench cold-starts closed and ignores this on launch. */
export function readStoredRightSidebarOpen(): boolean {
  return readBoolean(OPEN_KEY, false)
}

export function persistRightSidebarOpen(open: boolean): void {
  persistBoolean(OPEN_KEY, open)
}

export function readStoredRightSidebarCollapsed(): boolean {
  return readBoolean(COLLAPSED_KEY, false)
}

export function persistRightSidebarCollapsed(collapsed: boolean): void {
  persistBoolean(COLLAPSED_KEY, collapsed)
}
