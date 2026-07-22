import { create } from 'zustand'
import { isImagePreviewPath } from '@shared/image-preview'

export type EditorTabKind = 'text' | 'image'
export type EditorPaneId = 'primary' | 'secondary'

export type EditorTab = {
  id: string
  path: string
  kind: EditorTabKind
  content: string
  savedContent: string
  loading: boolean
  error: string | null
  line?: number
  column?: number
}

export type OpenFileOptions = {
  /** Open into the other pane and enable split. */
  toSide?: boolean
  pane?: EditorPaneId
}

type WorkspaceEditorStore = {
  tabs: EditorTab[]
  activeTabId: string | null
  secondaryTabId: string | null
  focusedPane: EditorPaneId
  splitEnabled: boolean
  workspaceKey: string
  openFile: (
    path: string,
    workspaceRoot: string,
    line?: number,
    column?: number,
    options?: OpenFileOptions
  ) => Promise<void>
  closeTab: (tabId: string) => void
  setActiveTab: (tabId: string, pane?: EditorPaneId) => void
  setFocusedPane: (pane: EditorPaneId) => void
  closeSplit: () => void
  updateTabContent: (tabId: string, content: string) => void
  saveTab: (tabId: string, workspaceRoot: string) => Promise<boolean>
  saveActiveTab: (workspaceRoot: string) => Promise<boolean>
  resetForWorkspace: (workspaceKey: string) => void
}

function normalizeWorkspaceKey(workspaceRoot: string): string {
  return workspaceRoot.trim().replace(/\\/g, '/').replace(/\/+$/, '')
}

export function normalizeEditorPathForTab(path: string): string {
  return path.replace(/\\/g, '/').replace(/\/+$/, '')
}

function isDirty(tab: EditorTab): boolean {
  return tab.content !== tab.savedContent
}

function upsertTab(tabs: EditorTab[], tab: EditorTab): EditorTab[] {
  const index = tabs.findIndex((entry) => entry.id === tab.id)
  if (index === -1) return [...tabs, tab]
  const next = tabs.slice()
  next[index] = tab
  return next
}

function resolveTargetPane(
  state: Pick<WorkspaceEditorStore, 'focusedPane' | 'splitEnabled'>,
  options?: OpenFileOptions
): EditorPaneId {
  if (options?.toSide) return 'secondary'
  if (options?.pane) return options.pane
  if (state.splitEnabled && state.focusedPane === 'secondary') return 'secondary'
  return 'primary'
}

function paneAssignment(
  tabId: string,
  pane: EditorPaneId,
  toSide: boolean
): Partial<
  Pick<
    WorkspaceEditorStore,
    'activeTabId' | 'secondaryTabId' | 'focusedPane' | 'splitEnabled'
  >
> {
  if (toSide || pane === 'secondary') {
    return {
      secondaryTabId: tabId,
      splitEnabled: true,
      focusedPane: 'secondary'
    }
  }
  return {
    activeTabId: tabId,
    focusedPane: 'primary'
  }
}

export const useWorkspaceEditorStore = create<WorkspaceEditorStore>((set, get) => ({
  tabs: [],
  activeTabId: null,
  secondaryTabId: null,
  focusedPane: 'primary',
  splitEnabled: false,
  workspaceKey: '',
  resetForWorkspace: (workspaceKey) => {
    const next = normalizeWorkspaceKey(workspaceKey)
    const prev = get().workspaceKey
    if (prev === next) return
    const shouldClearTabs = prev.length > 0 && next.length > 0 && prev !== next
    set({
      tabs: shouldClearTabs ? [] : get().tabs,
      activeTabId: shouldClearTabs ? null : get().activeTabId,
      secondaryTabId: shouldClearTabs ? null : get().secondaryTabId,
      splitEnabled: shouldClearTabs ? false : get().splitEnabled,
      focusedPane: shouldClearTabs ? 'primary' : get().focusedPane,
      workspaceKey: next.length > 0 ? next : prev
    })
  },
  openFile: async (path, workspaceRoot, line, column, options) => {
    const root = normalizeWorkspaceKey(workspaceRoot)
    if (!root) return

    const normalizedPath = normalizeEditorPathForTab(path)
    if (!normalizedPath) return

    const id = normalizedPath
    get().resetForWorkspace(root)

    const toSide = Boolean(options?.toSide)
    const targetPane = resolveTargetPane(get(), options)

    const existing = get().tabs.find((tab) => tab.id === id)
    if (existing && !existing.loading) {
      set((state) => ({
        // Re-opening an already-loaded tab with a position retargets it, so
        // the editor surface re-reveals the newly requested line.
        tabs:
          line !== undefined || column !== undefined
            ? upsertTab(state.tabs, { ...existing, line, column })
            : state.tabs,
        ...paneAssignment(id, targetPane, toSide)
      }))
      return
    }

    const kind: EditorTabKind = isImagePreviewPath(normalizedPath) ? 'image' : 'text'
    const placeholder: EditorTab = {
      id,
      path: normalizedPath,
      kind,
      content: '',
      savedContent: '',
      loading: true,
      error: null,
      line,
      column
    }
    set((state) => ({
      tabs: upsertTab(state.tabs, placeholder),
      ...paneAssignment(id, targetPane, toSide)
    }))

    if (kind === 'image') {
      set((state) => ({
        tabs: upsertTab(state.tabs, {
          ...placeholder,
          loading: false
        })
      }))
      return
    }

    if (typeof window.dsGui?.readWorkspaceFile !== 'function') {
      set((state) => ({
        tabs: upsertTab(state.tabs, {
          ...placeholder,
          loading: false,
          error: 'File bridge is unavailable.'
        })
      }))
      return
    }

    try {
      const result = await window.dsGui.readWorkspaceFile({
        path: normalizedPath,
        workspaceRoot: root,
        line,
        column
      })

      const currentKey = normalizeWorkspaceKey(get().workspaceKey)
      if (currentKey !== root && currentKey !== '') return

      const nextTab: EditorTab =
        !result.ok
          ? {
              ...placeholder,
              loading: false,
              error: result.message
            }
          : {
              id,
              path: normalizedPath,
              kind: 'text',
              content: result.content,
              savedContent: result.content,
              loading: false,
              error: result.truncated ? 'File truncated for preview; edits may be limited.' : null,
              line,
              column
            }

      set((state) => ({
        tabs: upsertTab(state.tabs, nextTab)
      }))
    } catch (error) {
      const currentKey = normalizeWorkspaceKey(get().workspaceKey)
      if (currentKey !== root && currentKey !== '') return
      set((state) => ({
        tabs: upsertTab(state.tabs, {
          ...placeholder,
          loading: false,
          error: error instanceof Error ? error.message : String(error)
        })
      }))
    }
  },
  closeTab: (tabId) =>
    set((state) => {
      const nextTabs = state.tabs.filter((tab) => tab.id !== tabId)
      let activeTabId =
        state.activeTabId === tabId
          ? (nextTabs[nextTabs.length - 1]?.id ?? null)
          : state.activeTabId
      let secondaryTabId =
        state.secondaryTabId === tabId ? null : state.secondaryTabId
      let splitEnabled = state.splitEnabled
      let focusedPane = state.focusedPane

      if (secondaryTabId === null) {
        splitEnabled = false
        focusedPane = 'primary'
      }

      if (activeTabId === null && secondaryTabId) {
        activeTabId = secondaryTabId
        secondaryTabId = null
        splitEnabled = false
        focusedPane = 'primary'
      }

      if (activeTabId === secondaryTabId) {
        secondaryTabId = null
        splitEnabled = false
        focusedPane = 'primary'
      }

      return {
        tabs: nextTabs,
        activeTabId,
        secondaryTabId,
        splitEnabled,
        focusedPane
      }
    }),
  setActiveTab: (tabId, pane) =>
    set((state) => {
      const target = pane ?? (state.splitEnabled ? state.focusedPane : 'primary')
      if (target === 'secondary' && state.splitEnabled) {
        return { secondaryTabId: tabId, focusedPane: 'secondary' }
      }
      return { activeTabId: tabId, focusedPane: 'primary' }
    }),
  setFocusedPane: (pane) => set({ focusedPane: pane }),
  closeSplit: () =>
    set((state) => {
      const keepId =
        state.focusedPane === 'secondary' && state.secondaryTabId
          ? state.secondaryTabId
          : state.activeTabId
      return {
        activeTabId: keepId,
        secondaryTabId: null,
        splitEnabled: false,
        focusedPane: 'primary'
      }
    }),
  updateTabContent: (tabId, content) =>
    set((state) => ({
      tabs: state.tabs.map((tab) => (tab.id === tabId ? { ...tab, content } : tab))
    })),
  saveTab: async (tabId, workspaceRoot) => {
    const root = normalizeWorkspaceKey(workspaceRoot)
    if (!tabId || !root) return false
    const tab = get().tabs.find((entry) => entry.id === tabId)
    if (!tab || tab.loading || tab.kind === 'image' || !isDirty(tab)) return true
    if (typeof window.dsGui?.writeWorkspaceFile !== 'function') return false

    const result = await window.dsGui.writeWorkspaceFile({
      path: tab.path,
      workspaceRoot: root,
      content: tab.content
    })
    if (!result.ok) {
      set((state) => ({
        tabs: state.tabs.map((entry) =>
          entry.id === tab.id ? { ...entry, error: result.message } : entry
        )
      }))
      return false
    }

    set((state) => ({
      tabs: state.tabs.map((entry) =>
        entry.id === tab.id
          ? {
              ...entry,
              savedContent: entry.content,
              error: null,
              path: normalizeEditorPathForTab(entry.path)
            }
          : entry
      )
    }))
    return true
  },
  saveActiveTab: async (workspaceRoot) => {
    const { focusedPane, activeTabId, secondaryTabId, splitEnabled } = get()
    const tabId =
      splitEnabled && focusedPane === 'secondary' ? secondaryTabId : activeTabId
    if (!tabId) return false
    return get().saveTab(tabId, workspaceRoot)
  }
}))
