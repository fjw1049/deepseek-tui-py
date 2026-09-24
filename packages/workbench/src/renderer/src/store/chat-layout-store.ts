import { create } from 'zustand'
import { normalizeWorkspaceRoot } from '../lib/workspace-path'

export const MAX_CHAT_PANES = 6
export const CHAT_THREAD_DRAG_MIME = 'application/x-deepseek-thread'
export type ChatPane = { id: string; threadId: string | null }
export type ParkedChatPane = ChatPane & { index: number }
export type ChatArrangement = 'grid' | 'horizontal' | 'vertical' | 'tabs'
export type ChatLayout = { arrangement?: ChatArrangement; parked?: ParkedChatPane[]; panes: ChatPane[]; focused: string; x: number; y: number }
const STORAGE_KEY = 'deepseek.chat-layouts.v1'
export const chatProjectKey = (path: string): string => normalizeWorkspaceRoot(path)

export function sanitizeChatLayout(value: unknown): ChatLayout | null {
  if (!value || typeof value !== 'object') return null
  const raw = value as Partial<ChatLayout>
  if (!Array.isArray(raw.panes)) return null
  const ids = new Set<string>()
  const threads = new Set<string>()
  const panes = raw.panes.filter((pane): pane is ChatPane => {
    if (!pane || typeof pane.id !== 'string' || !pane.id || ids.has(pane.id)) return false
    if (pane.threadId !== null && (typeof pane.threadId !== 'string' || threads.has(pane.threadId))) return false
    ids.add(pane.id)
    if (pane.threadId) threads.add(pane.threadId)
    return true
  }).slice(0, MAX_CHAT_PANES).map(({ id, threadId }) => ({ id, threadId }))
  const parked = (Array.isArray(raw.parked) ? raw.parked : []).flatMap(pane => {
    if (!pane || typeof pane.id !== 'string' || !pane.id || ids.has(pane.id) ||
        typeof pane.threadId !== 'string' || !pane.threadId || threads.has(pane.threadId)) return []
    ids.add(pane.id); threads.add(pane.threadId)
    return [{ id: pane.id, threadId: pane.threadId, index: Number.isInteger(pane.index) ? Math.max(0, Math.min(MAX_CHAT_PANES - 1, pane.index)) : 0 }]
  })
  if (!panes.length) return null
  const ratio = (v: unknown): number => typeof v === 'number' && Number.isFinite(v) ? Math.max(.25, Math.min(.75, v)) : .5
  return { parked, arrangement: raw.arrangement === 'horizontal' || raw.arrangement === 'vertical' || raw.arrangement === 'tabs' ? raw.arrangement : 'grid', panes, focused: panes.some(p => p.id === raw.focused) ? raw.focused! : panes[0].id, x: ratio(raw.x), y: ratio(raw.y) }
}

function loadLayouts(): Record<string, ChatLayout> {
  try {
    const raw = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? '{}')
    return Object.fromEntries(Object.entries(raw).flatMap(([key, value]) => {
      const layout = sanitizeChatLayout(value)
      return layout ? [[key, layout]] : []
    }))
  } catch { return {} }
}

export function resolveChatLayoutKey(state: Pick<LayoutState, 'activeLayoutKey' | 'layouts'>, workspace: string): string {
  return state.activeLayoutKey && state.layouts[state.activeLayoutKey]
    ? state.activeLayoutKey : chatProjectKey(workspace)
}

/** Saved splits become visible only after a navigation action in this session. */
export function activeChatLayout(state: Pick<LayoutState, 'activeLayoutKey' | 'layouts'>, workspace: string): ChatLayout | undefined {
  return state.activeLayoutKey ? state.layouts[resolveChatLayoutKey(state, workspace)] : undefined
}

type LayoutState = {
  activeLayoutKey: string | null
  layouts: Record<string, ChatLayout>
  add: (project: string, current: string | null, threadId?: string | null, side?: 'left' | 'right') => boolean
  bind: (project: string, paneId: string, threadId: string) => void
  drop: (project: string, paneId: string, threadId: string) => boolean
  focus: (project: string, paneId: string) => void
  close: (project: string, paneId: string) => void
  park: (project: string, paneId: string) => void
  restore: (project: string, paneId: string, targetId?: string) => boolean
  dismissParked: (project: string, paneId: string) => void
  resize: (project: string, axis: 'x' | 'y', ratio: number) => void
  arrange: (project: string, arrangement: ChatArrangement) => void
  reconcile: (project: string, validIds: string[]) => void
}

export const useChatLayoutStore = create<LayoutState>((set, get) => {
  const update = (project: string, layout: ChatLayout): void => {
    const clean = sanitizeChatLayout(layout)
    if (!clean) return
    const layouts = { ...get().layouts, [chatProjectKey(project)]: clean }
    set({ layouts, activeLayoutKey: chatProjectKey(project) })
    try { window.localStorage.setItem(STORAGE_KEY, JSON.stringify(layouts)) } catch { /* storage may be unavailable */ }
  }
  return {
    layouts: loadLayouts(),
    activeLayoutKey: null,
    add(project, current, threadId = null, side = 'right') {
      const layout = get().layouts[chatProjectKey(project)] ?? {
        panes: [{ id: crypto.randomUUID(), threadId: current }], focused: '', x: .5, y: .5
      }
      const existing = threadId && layout.panes.find(p => p.threadId === threadId)
      if (existing) { update(project, { ...layout, focused: existing.id }); return true }
      const parked = layout.parked?.find(p => p.threadId === threadId)
      if (parked) return get().restore(project, parked.id)
      if (layout.panes.length >= MAX_CHAT_PANES) return false
      const pane = { id: crypto.randomUUID(), threadId }
      update(project, { ...layout, panes: side === 'left' ? [pane, ...layout.panes] : [...layout.panes, pane], focused: pane.id })
      return true
    },
    bind(project, paneId, threadId) {
      const layout = get().layouts[chatProjectKey(project)]
      if (!layout) return
      const existing = layout.panes.find(p => p.threadId === threadId)
      if (existing) { update(project, { ...layout, focused: existing.id }); return }
      const parked = layout.parked?.find(p => p.threadId === threadId)
      if (parked) { get().restore(project, parked.id, paneId); return }
      update(project, { ...layout, panes: layout.panes.map(p => p.id === paneId ? { ...p, threadId } : p), focused: paneId })
    },
    drop(project, paneId, threadId) {
      const layout = get().layouts[chatProjectKey(project)]
      if (!layout) return false
      const target = layout.panes.findIndex(p => p.id === paneId)
      if (target < 0) return false
      const parked = layout.parked?.find(p => p.threadId === threadId)
      if (parked) return get().restore(project, parked.id, paneId)
      const source = layout.panes.findIndex(p => p.threadId === threadId)
      const panes = [...layout.panes]
      if (source >= 0) {
        const dragged = panes[source]
        panes[source] = panes[target]
        panes[target] = dragged
      } else {
        panes[target] = { ...panes[target], threadId }
      }
      update(project, { ...layout, panes, focused: panes[target].id })
      return true
    },
    focus(project, paneId) {
      const layout = get().layouts[chatProjectKey(project)]
      if (layout?.panes.some(p => p.id === paneId)) update(project, { ...layout, focused: paneId })
    },
    close(project, paneId) {
      const layout = get().layouts[chatProjectKey(project)]
      if (!layout || layout.panes.length <= 1) return
      const panes = layout.panes.filter(p => p.id !== paneId)
      update(project, { ...layout, panes, focused: layout.focused === paneId ? panes[0].id : layout.focused })
    },
    park(project, paneId) {
      const layout = get().layouts[chatProjectKey(project)]
      const index = layout?.panes.findIndex(p => p.id === paneId) ?? -1
      if (!layout || index < 0 || !layout.panes[index].threadId) return
      const panes = layout.panes.filter(p => p.id !== paneId)
      if (!panes.length) panes.push({ id: crypto.randomUUID(), threadId: null })
      update(project, { ...layout, panes, parked: [...(layout.parked ?? []), { ...layout.panes[index], index }],
        focused: layout.focused === paneId ? panes[Math.min(index, panes.length - 1)].id : layout.focused })
    },
    restore(project, paneId, targetId) {
      const layout = get().layouts[chatProjectKey(project)]
      const entry = layout?.parked?.find(p => p.id === paneId)
      if (!layout || !entry) return false
      const panes = [...layout.panes]
      const target = targetId ? panes.findIndex(p => p.id === targetId) : panes.findIndex(p => !p.threadId)
      if (targetId && target < 0 || target < 0 && panes.length >= MAX_CHAT_PANES) return false
      const parked = layout.parked!.filter(p => p.id !== paneId)
      const pane = { id: entry.id, threadId: entry.threadId }
      if (target >= 0) {
        if (panes[target].threadId) parked.push({ ...panes[target], index: target })
        panes[target] = pane
      } else panes.splice(Math.min(entry.index, panes.length), 0, pane)
      update(project, { ...layout, panes, parked, focused: pane.id })
      return true
    },
    dismissParked(project, paneId) {
      const layout = get().layouts[chatProjectKey(project)]
      if (layout) update(project, { ...layout, parked: layout.parked?.filter(p => p.id !== paneId) })
    },
    resize(project, axis, ratio) {
      const layout = get().layouts[chatProjectKey(project)]
      if (layout) update(project, { ...layout, [axis]: ratio })
    },
    arrange(project, arrangement) {
      const layout = get().layouts[chatProjectKey(project)]
      if (layout) update(project, { ...layout, arrangement })
    },
    reconcile(project, validIds) {
      const layout = get().layouts[chatProjectKey(project)]
      if (!layout) return
      const valid = new Set(validIds)
      if (layout.panes.some(p => p.threadId && !valid.has(p.threadId)) || layout.parked?.some(p => !valid.has(p.threadId!))) {
        update(project, { ...layout, parked: layout.parked?.filter(p => valid.has(p.threadId!)), panes: layout.panes.map(p => p.threadId && !valid.has(p.threadId) ? { ...p, threadId: null } : p) })
      }
    }
  }
})
