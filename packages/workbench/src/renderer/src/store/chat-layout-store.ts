import { create } from 'zustand'
import { normalizeWorkspaceRoot } from '../lib/workspace-path'

export const MAX_CHAT_PANES = 4
export const CHAT_THREAD_DRAG_MIME = 'application/x-deepseek-thread'
export type ChatPane = { id: string; threadId: string | null }
export type ChatArrangement = 'grid' | 'horizontal' | 'vertical'
export type ChatLayout = { arrangement?: ChatArrangement; panes: ChatPane[]; focused: string; x: number; y: number }
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
  if (!panes.length) return null
  const ratio = (v: unknown): number => typeof v === 'number' && Number.isFinite(v) ? Math.max(.25, Math.min(.75, v)) : .5
  return { arrangement: raw.arrangement === 'horizontal' || raw.arrangement === 'vertical' ? raw.arrangement : 'grid', panes, focused: panes.some(p => p.id === raw.focused) ? raw.focused! : panes[0].id, x: ratio(raw.x), y: ratio(raw.y) }
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

function loadActiveLayoutKey(): string | null {
  try { return window.localStorage.getItem('deepseek.chat-layout-active.v1') } catch { return null }
}

type LayoutState = {
  activeLayoutKey: string | null
  layouts: Record<string, ChatLayout>
  add: (project: string, current: string | null, threadId?: string | null, side?: 'left' | 'right') => boolean
  bind: (project: string, paneId: string, threadId: string) => void
  focus: (project: string, paneId: string) => void
  close: (project: string, paneId: string) => void
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
    try { window.localStorage.setItem(STORAGE_KEY, JSON.stringify(layouts)); window.localStorage.setItem('deepseek.chat-layout-active.v1', chatProjectKey(project)) } catch { /* storage may be unavailable */ }
  }
  return {
    layouts: loadLayouts(),
    activeLayoutKey: loadActiveLayoutKey(),
    add(project, current, threadId = null, side = 'right') {
      const layout = get().layouts[chatProjectKey(project)] ?? {
        panes: [{ id: crypto.randomUUID(), threadId: current }], focused: '', x: .5, y: .5
      }
      const existing = threadId && layout.panes.find(p => p.threadId === threadId)
      if (existing) { update(project, { ...layout, focused: existing.id }); return true }
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
      update(project, { ...layout, panes: layout.panes.map(p => p.id === paneId ? { ...p, threadId } : p), focused: paneId })
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
      if (layout.panes.some(p => p.threadId && !valid.has(p.threadId))) {
        update(project, { ...layout, panes: layout.panes.map(p => p.threadId && !valid.has(p.threadId) ? { ...p, threadId: null } : p) })
      }
    }
  }
})
