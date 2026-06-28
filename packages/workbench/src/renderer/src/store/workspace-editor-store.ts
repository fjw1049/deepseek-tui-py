import { create } from 'zustand'

export type EditorTab = {
  id: string
  path: string
  content: string
  savedContent: string
  loading: boolean
  error: string | null
  line?: number
  column?: number
}

type WorkspaceEditorStore = {
  tabs: EditorTab[]
  activeTabId: string | null
  workspaceKey: string
  openFile: (path: string, workspaceRoot: string, line?: number, column?: number) => Promise<void>
  closeTab: (tabId: string) => void
  setActiveTab: (tabId: string) => void
  updateTabContent: (tabId: string, content: string) => void
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

function upsertTab(
  tabs: EditorTab[],
  tab: EditorTab
): { tabs: EditorTab[]; activeTabId: string } {
  const index = tabs.findIndex((entry) => entry.id === tab.id)
  if (index === -1) {
    return { tabs: [...tabs, tab], activeTabId: tab.id }
  }
  const next = tabs.slice()
  next[index] = tab
  return { tabs: next, activeTabId: tab.id }
}

export const useWorkspaceEditorStore = create<WorkspaceEditorStore>((set, get) => ({
  tabs: [],
  activeTabId: null,
  workspaceKey: '',
  resetForWorkspace: (workspaceKey) => {
    const next = normalizeWorkspaceKey(workspaceKey)
    const prev = get().workspaceKey
    if (prev === next) return
    const shouldClearTabs = prev.length > 0 && next.length > 0 && prev !== next
    set({
      tabs: shouldClearTabs ? [] : get().tabs,
      activeTabId: shouldClearTabs ? null : get().activeTabId,
      workspaceKey: next.length > 0 ? next : prev
    })
  },
  openFile: async (path, workspaceRoot, line, column) => {
    const root = normalizeWorkspaceKey(workspaceRoot)
    if (!root) return

    const normalizedPath = normalizeEditorPathForTab(path)
    if (!normalizedPath) return

    const id = normalizedPath
    get().resetForWorkspace(root)

    const existing = get().tabs.find((tab) => tab.id === id)
    if (existing && !existing.loading) {
      set({ activeTabId: id })
      return
    }

    const placeholder: EditorTab = {
      id,
      path: normalizedPath,
      content: '',
      savedContent: '',
      loading: true,
      error: null,
      line,
      column
    }
    set((state) => upsertTab(state.tabs, placeholder))

    if (typeof window.dsGui?.readWorkspaceFile !== 'function') {
      set((state) =>
        upsertTab(state.tabs, {
          ...placeholder,
          loading: false,
          error: 'File bridge is unavailable.'
        })
      )
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

      const nextTab: EditorTab = !result.ok
        ? {
            ...placeholder,
            loading: false,
            error: result.message
          }
        : {
            id,
            path: normalizedPath,
            content: result.content,
            savedContent: result.content,
            loading: false,
            error: result.truncated ? 'File truncated for preview; edits may be limited.' : null,
            line,
            column
          }

      set((state) => upsertTab(state.tabs, nextTab))
    } catch (error) {
      const currentKey = normalizeWorkspaceKey(get().workspaceKey)
      if (currentKey !== root && currentKey !== '') return
      set((state) =>
        upsertTab(state.tabs, {
          ...placeholder,
          loading: false,
          error: error instanceof Error ? error.message : String(error)
        })
      )
    }
  },
  closeTab: (tabId) =>
    set((state) => {
      const nextTabs = state.tabs.filter((tab) => tab.id !== tabId)
      const activeTabId =
        state.activeTabId === tabId ? (nextTabs[nextTabs.length - 1]?.id ?? null) : state.activeTabId
      return { tabs: nextTabs, activeTabId }
    }),
  setActiveTab: (tabId) => set({ activeTabId: tabId }),
  updateTabContent: (tabId, content) =>
    set((state) => ({
      tabs: state.tabs.map((tab) => (tab.id === tabId ? { ...tab, content } : tab))
    })),
  saveActiveTab: async (workspaceRoot) => {
    const root = normalizeWorkspaceKey(workspaceRoot)
    const { activeTabId, tabs } = get()
    if (!activeTabId || !root) return false
    const tab = tabs.find((entry) => entry.id === activeTabId)
    if (!tab || tab.loading || !isDirty(tab)) return true
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
          ? { ...entry, savedContent: entry.content, error: null, path: normalizeEditorPathForTab(entry.path) }
          : entry
      )
    }))
    return true
  }
}))
