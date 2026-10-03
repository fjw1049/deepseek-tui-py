import { create } from 'zustand'
import { terminalPaneIds, removeTerminalPane, replaceTerminalPane, resizeTerminalSplit, type TerminalLayout, type TerminalSplitDirection } from '../lib/terminal-layout'

const terminalOutput = new Map<string, { chunks: string[]; length: number }>()
const terminalExits = new Map<string, number>()
const OUTPUT_LIMIT = 1024 * 1024
const outputListeners = new Set<(event: { sessionId: string; data: string }) => void>()
const exitListeners = new Set<(event: { sessionId: string; exitCode: number }) => void>()
let stopTerminalEvents: (() => void) | undefined

function ensureTerminalEvents(): void {
  if (stopTerminalEvents || typeof window.dsGui?.onTerminalData !== 'function' ||
      typeof window.dsGui?.onTerminalExit !== 'function') return
  const offData = window.dsGui.onTerminalData((event) => {
    const state = useTerminalSessionStore.getState()
    if (!state.creatingSession && !state.sessions.some((session) => session.id === event.sessionId)) return
    const buffer = terminalOutput.get(event.sessionId) ?? { chunks: [], length: 0 }
    const data = event.data.slice(-OUTPUT_LIMIT)
    const last = buffer.chunks.length - 1
    if (last >= 0 && buffer.chunks[last].length < 4096) buffer.chunks[last] += data
    else buffer.chunks.push(data)
    buffer.length += data.length
    while (buffer.length > OUTPUT_LIMIT) {
      const excess = buffer.length - OUTPUT_LIMIT
      const first = buffer.chunks[0]
      if (first.length <= excess) { buffer.chunks.shift(); buffer.length -= first.length }
      else { buffer.chunks[0] = first.slice(excess); buffer.length -= excess }
    }
    terminalOutput.set(event.sessionId, buffer)
    for (const listener of outputListeners) listener(event)
  })
  const offExit = window.dsGui.onTerminalExit((event) => {
    const state = useTerminalSessionStore.getState()
    if (!state.creatingSession && !state.sessions.some((session) => session.id === event.sessionId)) return
    terminalExits.set(event.sessionId, event.exitCode)
    useTerminalSessionStore.getState().updateSession(event.sessionId, { status: 'exited', exitCode: event.exitCode })
    for (const listener of exitListeners) listener(event)
  })
  stopTerminalEvents = () => { offData(); offExit(); stopTerminalEvents = undefined }
}

export function readTerminalOutput(sessionId: string): string {
  return terminalOutput.get(sessionId)?.chunks.join('') ?? ''
}

export function subscribeTerminalEvents(
  onData: (event: { sessionId: string; data: string }) => void,
  onExit: (event: { sessionId: string; exitCode: number }) => void
): () => void {
  ensureTerminalEvents()
  outputListeners.add(onData)
  exitListeners.add(onExit)
  return () => { outputListeners.delete(onData); exitListeners.delete(onExit) }
}

export type TerminalSessionInfo = {
  id: string
  cwd: string
  status: 'running' | 'exited'
  exitCode?: number
}

export type TerminalXtermMount = 'bottom' | 'sidebar'

type TerminalSessionStore = {
  sessions: TerminalSessionInfo[]
  activeSessionId: string | null
  layouts: TerminalLayout[]
  creatingSession: boolean
  createError: string | null
  xtermMount: TerminalXtermMount
  hasStartedInitialSession: boolean
  setXtermMount: (mount: TerminalXtermMount) => void
  setActiveSessionId: (sessionId: string | null) => void
  resizeSplit: (id: string, ratio: number) => void
  setCreatingSession: (creating: boolean) => void
  setCreateError: (message: string | null) => void
  addSession: (session: TerminalSessionInfo, split?: { targetId: string; direction: TerminalSplitDirection }) => void
  updateSession: (sessionId: string, patch: Partial<TerminalSessionInfo>) => void
  removeSession: (sessionId: string) => void
  resetSessions: () => void
  markInitialSessionStarted: () => void
}

export const useTerminalSessionStore = create<TerminalSessionStore>((set) => ({
  sessions: [],
  activeSessionId: null,
  layouts: [],
  creatingSession: false,
  createError: null,
  xtermMount: 'bottom',
  hasStartedInitialSession: false,
  setXtermMount: (mount) => set({ xtermMount: mount }),
  setActiveSessionId: (sessionId) => set({ activeSessionId: sessionId }),
  resizeSplit: (id, ratio) => set((state) => ({ layouts: state.layouts.map((node) => resizeTerminalSplit(node, id, ratio)) })),
  setCreatingSession: (creating) => set({ creatingSession: creating }),
  setCreateError: (message) => set({ createError: message }),
  addSession: (session, split) =>
    set((state) => {
      ensureTerminalEvents()
      const exitCode = terminalExits.get(session.id)
      if (exitCode !== undefined) session = { ...session, status: 'exited', exitCode }
      const pane: TerminalLayout = { type: 'pane', id: session.id }
      const targetExists = split && state.layouts.some((node) => terminalPaneIds(node).includes(split.targetId))
      return {
        sessions: [...state.sessions, session],
        activeSessionId: session.id,
        layouts: targetExists ? state.layouts.map((node) => replaceTerminalPane(node, split.targetId, {
          type: 'split', id: `split-${session.id}`, direction: split.direction, ratio: 0.5,
          first: { type: 'pane', id: split.targetId }, second: pane
        })) : [...state.layouts, pane]
      }
    }),
  updateSession: (sessionId, patch) =>
    set((state) => ({
      sessions: state.sessions.map((session) =>
        session.id === sessionId ? { ...session, ...patch } : session
      )
    })),
  removeSession: (sessionId) =>
    set((state) => {
      terminalOutput.delete(sessionId)
      terminalExits.delete(sessionId)
      const next = state.sessions.filter((session) => session.id !== sessionId)
      if (next.length === 0) stopTerminalEvents?.()
      const group = state.layouts.find((node) => terminalPaneIds(node).includes(sessionId))
      const neighbor = group && terminalPaneIds(group).find((id) => id !== sessionId)
      return {
        sessions: next,
        activeSessionId: state.activeSessionId === sessionId ? neighbor || next[0]?.id || null : state.activeSessionId,
        layouts: state.layouts.map((node) => removeTerminalPane(node, sessionId)).filter((node): node is TerminalLayout => node !== null)
      }
    }),
  resetSessions: () => {
    terminalOutput.clear()
    terminalExits.clear()
    stopTerminalEvents?.()
    set({
      sessions: [],
      activeSessionId: null,
      layouts: [],
      creatingSession: false,
      createError: null,
      hasStartedInitialSession: false
    })
  },
  markInitialSessionStarted: () => set({ hasStartedInitialSession: true })
}))

export type TerminalCreateDimensions = {
  cols: number
  rows: number
}

export async function createTerminalSessionForWorkspace(
  workspaceRoot: string,
  dimensions?: TerminalCreateDimensions,
  split?: { targetId: string; direction: TerminalSplitDirection }
): Promise<boolean> {
  const cwd = workspaceRoot.trim()
  if (!cwd || typeof window.dsGui?.createTerminalSession !== 'function') return false

  const store = useTerminalSessionStore.getState()
  if (store.creatingSession) return false

  const cols = Math.max(20, Math.floor(dimensions?.cols ?? 120))
  const rows = Math.max(8, Math.floor(dimensions?.rows ?? 32))

  ensureTerminalEvents()
  store.setCreatingSession(true)
  store.setCreateError(null)
  try {
    const result = await window.dsGui.createTerminalSession({
      cwd,
      cols,
      rows
    })
    if (!result.ok) {
      store.setCreateError(result.message)
      return false
    }
    store.addSession({
      id: result.session.id,
      cwd: result.session.cwd,
      status: 'running'
    }, split)
    return true
  } catch (error) {
    store.setCreateError(error instanceof Error ? error.message : String(error))
    return false
  } finally {
    store.setCreatingSession(false)
  }
}

export function closeTerminalSessionById(sessionId: string): void {
  void window.dsGui?.closeTerminalSession?.({ sessionId })
  useTerminalSessionStore.getState().removeSession(sessionId)
}

export function closeAllTerminalSessions(): void {
  const { sessions } = useTerminalSessionStore.getState()
  for (const session of sessions) {
    void window.dsGui?.closeTerminalSession?.({ sessionId: session.id })
  }
  useTerminalSessionStore.getState().resetSessions()
}

/** Split the focused pane without changing its existing siblings. */
export async function splitTerminalSession(workspaceRoot: string, direction: TerminalSplitDirection): Promise<void> {
  const store = useTerminalSessionStore.getState()
  const target = store.sessions.find((session) => session.id === store.activeSessionId)
  if (!target) return
  await createTerminalSessionForWorkspace(target.cwd || workspaceRoot, undefined, { targetId: target.id, direction })
}
