import { create } from 'zustand'

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
  creatingSession: boolean
  createError: string | null
  xtermMount: TerminalXtermMount
  hasStartedInitialSession: boolean
  setXtermMount: (mount: TerminalXtermMount) => void
  setActiveSessionId: (sessionId: string | null) => void
  setCreatingSession: (creating: boolean) => void
  setCreateError: (message: string | null) => void
  addSession: (session: TerminalSessionInfo) => void
  updateSession: (sessionId: string, patch: Partial<TerminalSessionInfo>) => void
  removeSession: (sessionId: string) => void
  resetSessions: () => void
  markInitialSessionStarted: () => void
}

export const useTerminalSessionStore = create<TerminalSessionStore>((set, get) => ({
  sessions: [],
  activeSessionId: null,
  creatingSession: false,
  createError: null,
  xtermMount: 'bottom',
  hasStartedInitialSession: false,
  setXtermMount: (mount) => set({ xtermMount: mount }),
  setActiveSessionId: (sessionId) => set({ activeSessionId: sessionId }),
  setCreatingSession: (creating) => set({ creatingSession: creating }),
  setCreateError: (message) => set({ createError: message }),
  addSession: (session) =>
    set((state) => ({
      sessions: [...state.sessions, session],
      activeSessionId: session.id
    })),
  updateSession: (sessionId, patch) =>
    set((state) => ({
      sessions: state.sessions.map((session) =>
        session.id === sessionId ? { ...session, ...patch } : session
      )
    })),
  removeSession: (sessionId) =>
    set((state) => {
      const next = state.sessions.filter((session) => session.id !== sessionId)
      const activeSessionId =
        state.activeSessionId === sessionId ? (next[0]?.id ?? null) : state.activeSessionId
      return { sessions: next, activeSessionId }
    }),
  resetSessions: () =>
    set({
      sessions: [],
      activeSessionId: null,
      creatingSession: false,
      createError: null,
      hasStartedInitialSession: false
    }),
  markInitialSessionStarted: () => set({ hasStartedInitialSession: true })
}))

export async function createTerminalSessionForWorkspace(workspaceRoot: string): Promise<boolean> {
  const cwd = workspaceRoot.trim()
  if (!cwd || typeof window.dsGui?.createTerminalSession !== 'function') return false

  const store = useTerminalSessionStore.getState()
  if (store.creatingSession) return false

  store.setCreatingSession(true)
  store.setCreateError(null)
  try {
    const result = await window.dsGui.createTerminalSession({
      cwd,
      cols: 120,
      rows: 32
    })
    if (!result.ok) {
      store.setCreateError(result.message)
      return false
    }
    store.addSession({
      id: result.session.id,
      cwd: result.session.cwd,
      status: 'running'
    })
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
