import { create } from 'zustand'
import { isImagePreviewPath } from '@shared/image-preview'
import type { WorkspaceFileReadResult } from '@shared/workspace-file'

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
  /** True when the on-disk file was truncated for preview — never write this buffer back. */
  truncated?: boolean
  line?: number
  column?: number
  /** Bumped on each open-at-line request so the surface re-reveals even for the same line. */
  revealNonce?: number
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
  /** Tabs shown in the left/primary strip, in order. */
  primaryTabIds: string[]
  /** Tabs shown in the right strip while split, in order. */
  secondaryTabIds: string[]
  focusedPane: EditorPaneId
  splitEnabled: boolean
  workspaceKey: string
  openFile: (
    path: string,
    workspaceRoot: string,
    line?: number,
    column?: number,
    options?: OpenFileOptions
  ) => Promise<boolean>
  closeTab: (tabId: string, pane?: EditorPaneId) => void
  setActiveTab: (tabId: string, pane?: EditorPaneId) => void
  setFocusedPane: (pane: EditorPaneId) => void
  closeSplit: () => void
  updateTabContent: (tabId: string, content: string) => void
  revertTab: (tabId: string) => void
  saveTab: (tabId: string, workspaceRoot: string) => Promise<boolean>
  saveActiveTab: (workspaceRoot: string) => Promise<boolean>
  /** Re-read clean (non-dirty) text tabs from disk after external changes (agent writes, rewind restore). */
  reloadCleanTabs: (workspaceRoot: string) => Promise<void>
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

function appendUnique(ids: string[], id: string): string[] {
  return ids.includes(id) ? ids : [...ids, id]
}

function neighborId(ids: string[], closedId: string): string | null {
  const index = ids.indexOf(closedId)
  if (index <= 0) return ids[1] ?? null
  return ids[index - 1] ?? ids[index + 1] ?? null
}

export function orderTabsByIds(tabs: EditorTab[], ids: string[]): EditorTab[] {
  const byId = new Map(tabs.map((tab) => [tab.id, tab]))
  return ids.flatMap((id) => {
    const tab = byId.get(id)
    return tab ? [tab] : []
  })
}

function hydratePaneIds(state: Pick<
  WorkspaceEditorStore,
  'tabs' | 'primaryTabIds' | 'secondaryTabIds' | 'splitEnabled' | 'secondaryTabId'
>): { primaryTabIds: string[]; secondaryTabIds: string[] } {
  let primaryTabIds = state.primaryTabIds
  let secondaryTabIds = state.secondaryTabIds
  if (primaryTabIds.length === 0 && state.tabs.length > 0) {
    primaryTabIds = state.tabs.map((tab) => tab.id)
  }
  if (
    state.splitEnabled &&
    secondaryTabIds.length === 0 &&
    state.secondaryTabId
  ) {
    secondaryTabIds = [state.secondaryTabId]
  }
  return { primaryTabIds, secondaryTabIds }
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

function resolveClosePane(
  state: Pick<
    WorkspaceEditorStore,
    'splitEnabled' | 'focusedPane' | 'primaryTabIds' | 'secondaryTabIds' | 'tabs' | 'secondaryTabId'
  >,
  tabId: string,
  pane?: EditorPaneId
): EditorPaneId {
  if (pane) return pane
  const { primaryTabIds, secondaryTabIds } = hydratePaneIds(state)
  if (
    state.splitEnabled &&
    state.focusedPane === 'secondary' &&
    secondaryTabIds.includes(tabId)
  ) {
    return 'secondary'
  }
  if (primaryTabIds.includes(tabId)) return 'primary'
  if (state.splitEnabled && secondaryTabIds.includes(tabId)) return 'secondary'
  return 'primary'
}

function assignTabToPane(
  state: Pick<
    WorkspaceEditorStore,
    | 'tabs'
    | 'primaryTabIds'
    | 'secondaryTabIds'
    | 'splitEnabled'
    | 'secondaryTabId'
    | 'activeTabId'
  >,
  tabId: string,
  targetPane: EditorPaneId,
  toSide: boolean
): Pick<
  WorkspaceEditorStore,
  | 'primaryTabIds'
  | 'secondaryTabIds'
  | 'activeTabId'
  | 'secondaryTabId'
  | 'focusedPane'
  | 'splitEnabled'
> {
  const { primaryTabIds, secondaryTabIds } = hydratePaneIds(state)
  if (toSide || targetPane === 'secondary') {
    const nextPrimary =
      primaryTabIds.length === 0 ? appendUnique(primaryTabIds, tabId) : primaryTabIds
    return {
      primaryTabIds: nextPrimary,
      secondaryTabIds: appendUnique(secondaryTabIds, tabId),
      activeTabId: state.activeTabId ?? tabId,
      secondaryTabId: tabId,
      splitEnabled: true,
      focusedPane: 'secondary'
    }
  }
  return {
    primaryTabIds: appendUnique(primaryTabIds, tabId),
    secondaryTabIds,
    activeTabId: tabId,
    secondaryTabId: state.secondaryTabId,
    splitEnabled: state.splitEnabled,
    focusedPane: 'primary'
  }
}

export const useWorkspaceEditorStore = create<WorkspaceEditorStore>((set, get) => ({
  tabs: [],
  activeTabId: null,
  secondaryTabId: null,
  primaryTabIds: [],
  secondaryTabIds: [],
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
      primaryTabIds: shouldClearTabs ? [] : get().primaryTabIds,
      secondaryTabIds: shouldClearTabs ? [] : get().secondaryTabIds,
      splitEnabled: shouldClearTabs ? false : get().splitEnabled,
      focusedPane: shouldClearTabs ? 'primary' : get().focusedPane,
      workspaceKey: next.length > 0 ? next : prev
    })
  },
  openFile: async (path, workspaceRoot, line, column, options) => {
    const root = normalizeWorkspaceKey(workspaceRoot)
    if (!root) return false

    const normalizedPath = normalizeEditorPathForTab(path)
    if (!normalizedPath) return false

    const id = normalizedPath
    get().resetForWorkspace(root)

    const toSide = Boolean(options?.toSide)
    const targetPane = resolveTargetPane(get(), options)

    const existing = get().tabs.find((tab) => tab.id === id)
    if (existing && !existing.error) {
      set((state) => ({
        tabs:
          line !== undefined || column !== undefined
            ? upsertTab(state.tabs, {
                ...existing,
                line,
                column,
                revealNonce: (existing.revealNonce ?? 0) + 1
              })
            : state.tabs,
        ...assignTabToPane(state, id, targetPane, toSide)
      }))
      return true
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
      column,
      revealNonce: line !== undefined || column !== undefined ? 1 : undefined
    }
    set((state) => ({
      tabs: upsertTab(state.tabs, placeholder),
      ...assignTabToPane(state, id, targetPane, toSide)
    }))

    if (kind === 'image') {
      set((state) => ({
        tabs: upsertTab(state.tabs, {
          ...placeholder,
          loading: false
        })
      }))
      return true
    }

    if (typeof window.dsGui?.readWorkspaceFile !== 'function') {
      set((state) => ({
        tabs: upsertTab(state.tabs, {
          ...placeholder,
          loading: false,
          error: 'File bridge is unavailable.'
        })
      }))
      return false
    }

    try {
      const result = await window.dsGui.readWorkspaceFile({
        path: normalizedPath,
        workspaceRoot: root,
        line,
        column
      })

      const currentKey = normalizeWorkspaceKey(get().workspaceKey)
      if (currentKey !== root && currentKey !== '') return false

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
              error: null,
              truncated: result.truncated,
              line,
              column,
              revealNonce: placeholder.revealNonce
            }

      set((state) => ({
        tabs: upsertTab(state.tabs, nextTab)
      }))
      return result.ok
    } catch (error) {
      const currentKey = normalizeWorkspaceKey(get().workspaceKey)
      if (currentKey !== root && currentKey !== '') return false
      set((state) => ({
        tabs: upsertTab(state.tabs, {
          ...placeholder,
          loading: false,
          error: error instanceof Error ? error.message : String(error)
        })
      }))
      return false
    }
  },
  closeTab: (tabId, pane) =>
    set((state) => {
      const hydrated = hydratePaneIds(state)
      let primaryTabIds = hydrated.primaryTabIds
      let secondaryTabIds = hydrated.secondaryTabIds
      let activeTabId = state.activeTabId
      let secondaryTabId = state.secondaryTabId
      let splitEnabled = state.splitEnabled
      let focusedPane = state.focusedPane
      const target = resolveClosePane(state, tabId, pane)

      if (target === 'secondary' && splitEnabled) {
        if (secondaryTabIds.includes(tabId)) {
          const nextIds = secondaryTabIds.filter((id) => id !== tabId)
          if (secondaryTabId === tabId) secondaryTabId = neighborId(secondaryTabIds, tabId)
          secondaryTabIds = nextIds
        }
      } else if (primaryTabIds.includes(tabId)) {
        const nextIds = primaryTabIds.filter((id) => id !== tabId)
        if (activeTabId === tabId) activeTabId = neighborId(primaryTabIds, tabId)
        primaryTabIds = nextIds
      }

      if (splitEnabled && secondaryTabIds.length === 0) {
        splitEnabled = false
        secondaryTabId = null
        focusedPane = 'primary'
      } else if (splitEnabled && primaryTabIds.length === 0) {
        primaryTabIds = secondaryTabIds
        activeTabId = secondaryTabId
        secondaryTabIds = []
        secondaryTabId = null
        splitEnabled = false
        focusedPane = 'primary'
      }

      const stillOpen =
        primaryTabIds.includes(tabId) ||
        (splitEnabled && secondaryTabIds.includes(tabId))
      return {
        tabs: stillOpen ? state.tabs : state.tabs.filter((tab) => tab.id !== tabId),
        primaryTabIds,
        secondaryTabIds,
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
      const { primaryTabIds, secondaryTabIds } = hydratePaneIds(state)
      const merged = secondaryTabIds.reduce(
        (ids, id) => appendUnique(ids, id),
        primaryTabIds
      )
      const keepId =
        state.focusedPane === 'secondary' && state.secondaryTabId
          ? state.secondaryTabId
          : state.activeTabId
      return {
        primaryTabIds: merged,
        secondaryTabIds: [],
        activeTabId:
          keepId && merged.includes(keepId)
            ? keepId
            : (merged[merged.length - 1] ?? null),
        secondaryTabId: null,
        splitEnabled: false,
        focusedPane: 'primary'
      }
    }),
  updateTabContent: (tabId, content) =>
    set((state) => ({
      tabs: state.tabs.map((tab) => (tab.id === tabId ? { ...tab, content } : tab))
    })),
  revertTab: (tabId) =>
    set((state) => ({
      tabs: state.tabs.map((tab) =>
        tab.id === tabId ? { ...tab, content: tab.savedContent } : tab
      )
    })),
  saveTab: async (tabId, workspaceRoot) => {
    const root = normalizeWorkspaceKey(workspaceRoot)
    if (!tabId || !root) return false
    const tab = get().tabs.find((entry) => entry.id === tabId)
    if (!tab || tab.loading || tab.kind === 'image') return true
    if (tab.truncated) return false
    if (!isDirty(tab)) return true
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
  },
  reloadCleanTabs: async (workspaceRoot) => {
    const root = normalizeWorkspaceKey(workspaceRoot)
    if (!root || typeof window.dsGui?.readWorkspaceFile !== 'function') return
    // Dirty tabs are never touched: an external change (agent write, rewind
    // restore) must not clobber the user's unsaved edits.
    const targets = get().tabs.filter(
      (tab) => tab.kind === 'text' && !tab.loading && !isDirty(tab)
    )
    await Promise.all(
      targets.map(async (target) => {
        let result: WorkspaceFileReadResult
        try {
          result = await window.dsGui.readWorkspaceFile({
            path: target.path,
            workspaceRoot: root
          })
        } catch (error) {
          result = {
            ok: false,
            message: error instanceof Error ? error.message : String(error)
          }
        }
        set((state) => {
          const currentKey = normalizeWorkspaceKey(state.workspaceKey)
          if (currentKey !== root && currentKey !== '') return {}
          return {
            tabs: state.tabs.map((entry) => {
              // Re-check: the user may have started editing (or closed) the
              // tab while the read was in flight.
              if (entry.id !== target.id || entry.loading || isDirty(entry)) return entry
              if (!result.ok) {
                // A restore can delete the file — surface it through the
                // tab's existing error banner instead of silently keeping
                // stale content that a later save would resurrect.
                return { ...entry, error: result.message }
              }
              return {
                ...entry,
                content: result.content,
                savedContent: result.content,
                error: null,
                truncated: result.truncated
              }
            })
          }
        })
      })
    )
  }
}))
