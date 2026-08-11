// Persists Workbench chat-vs-IDE layout mode and IDE-local chrome so re-entry
// restores the previous activity tab / chat-rail width without fighting the
// chat-mode right-sidebar maximize path (chatColumnHidden).

export type WorkbenchLayoutMode = 'chat' | 'ide'
export type IdeCenterTab = 'files' | 'changes' | 'search'

const LAYOUT_MODE_KEY = 'deepseekgui.layout.layoutMode'
const IDE_CENTER_TAB_KEY = 'deepseekgui.layout.ideCenterTab'
const IDE_CHAT_RAIL_WIDTH_KEY = 'deepseekgui.layout.ideChatRailWidth'
const IDE_ACTIVITY_SIDEBAR_VISIBLE_KEY = 'deepseekgui.layout.ideActivitySidebarVisible'

/** Comfortable fixed-ish rail: wide enough for CJK lines, still secondary to the editor. */
export const IDE_CHAT_RAIL_DEFAULT_WIDTH = 440
/** Floor fits iconized composer footer without crushing the textarea. */
export const IDE_CHAT_RAIL_MIN_WIDTH = 400
/** Wider max so dragging the rail left has more travel (editor stays primary). */
export const IDE_CHAT_RAIL_MAX_WIDTH = 800

const VALID_MODES = new Set<WorkbenchLayoutMode>(['chat', 'ide'])
const VALID_CENTER_TABS = new Set<IdeCenterTab>(['files', 'changes', 'search'])

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

export function clampIdeChatRailWidth(width: number): number {
  return Math.min(
    IDE_CHAT_RAIL_MAX_WIDTH,
    Math.max(IDE_CHAT_RAIL_MIN_WIDTH, Math.round(width))
  )
}

export function readStoredLayoutMode(): WorkbenchLayoutMode {
  try {
    const raw = window.localStorage.getItem(LAYOUT_MODE_KEY)
    if (raw && VALID_MODES.has(raw as WorkbenchLayoutMode)) {
      return raw as WorkbenchLayoutMode
    }
  } catch {
    /* ignore */
  }
  return 'chat'
}

export function persistLayoutMode(mode: WorkbenchLayoutMode): void {
  try {
    window.localStorage.setItem(LAYOUT_MODE_KEY, mode)
  } catch {
    /* ignore */
  }
}

export function readStoredIdeCenterTab(): IdeCenterTab {
  try {
    const raw = window.localStorage.getItem(IDE_CENTER_TAB_KEY)
    if (raw && VALID_CENTER_TABS.has(raw as IdeCenterTab)) {
      return raw as IdeCenterTab
    }
  } catch {
    /* ignore */
  }
  return 'files'
}

export function persistIdeCenterTab(tab: IdeCenterTab): void {
  try {
    window.localStorage.setItem(IDE_CENTER_TAB_KEY, tab)
  } catch {
    /* ignore */
  }
}

export function readStoredIdeChatRailWidth(): number {
  try {
    const raw = window.localStorage.getItem(IDE_CHAT_RAIL_WIDTH_KEY)
    if (!raw) return IDE_CHAT_RAIL_DEFAULT_WIDTH
    const parsed = Number(raw)
    if (!Number.isFinite(parsed)) return IDE_CHAT_RAIL_DEFAULT_WIDTH
    // Previous default (380) was too tight for CJK — treat it as unset.
    if (parsed === 380) return IDE_CHAT_RAIL_DEFAULT_WIDTH
    return clampIdeChatRailWidth(parsed)
  } catch {
    return IDE_CHAT_RAIL_DEFAULT_WIDTH
  }
}

export function persistIdeChatRailWidth(width: number): void {
  try {
    window.localStorage.setItem(
      IDE_CHAT_RAIL_WIDTH_KEY,
      String(clampIdeChatRailWidth(width))
    )
  } catch {
    /* ignore */
  }
}

export function readStoredIdeActivitySidebarVisible(): boolean {
  return readBoolean(IDE_ACTIVITY_SIDEBAR_VISIBLE_KEY, true)
}

export function persistIdeActivitySidebarVisible(visible: boolean): void {
  persistBoolean(IDE_ACTIVITY_SIDEBAR_VISIBLE_KEY, visible)
}

/** VS Code activity-bar toggle: click the active icon again to collapse the side panel. */
export function nextIdeActivitySelection(
  currentTab: IdeCenterTab,
  sidebarVisible: boolean,
  clicked: IdeCenterTab
): { tab: IdeCenterTab; sidebarVisible: boolean } {
  if (clicked === currentTab && sidebarVisible) {
    return { tab: currentTab, sidebarVisible: false }
  }
  return { tab: clicked, sidebarVisible: true }
}
