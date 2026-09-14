import { create } from 'zustand'
import { terminalPaneIds, removeTerminalPane, replaceTerminalPane, resizeTerminalSplit, type TerminalLayout, type TerminalSplitDirection } from '../lib/terminal-layout'

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
      const next = state.sessions.filter((session) => session.id !== sessionId)
      const group = state.layouts.find((node) => terminalPaneIds(node).includes(sessionId))
      const neighbor = group && terminalPaneIds(group).find((id) => id !== sessionId)
      return {
        sessions: next,
        activeSessionId: state.activeSessionId === sessionId ? neighbor || next[0]?.id || null : state.activeSessionId,
        layouts: state.layouts.map((node) => removeTerminalPane(node, sessionId)).filter((node): node is TerminalLayout => node !== null)
      }
    }),
  resetSessions: () =>
    set({
      sessions: [],
      activeSessionId: null,
      layouts: [],
      creatingSession: false,
      createError: null,
      hasStartedInitialSession: false
    }),
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
