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
  /** Bottom pane when IDE down-split is on; null = single pane. */
  splitSessionId: string | null
  creatingSession: boolean
  createError: string | null
  xtermMount: TerminalXtermMount
  hasStartedInitialSession: boolean
  setXtermMount: (mount: TerminalXtermMount) => void
  setActiveSessionId: (sessionId: string | null) => void
  setSplitSessionId: (sessionId: string | null) => void
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
  splitSessionId: null,
  creatingSession: false,
  createError: null,
  xtermMount: 'bottom',
  hasStartedInitialSession: false,
  setXtermMount: (mount) => set({ xtermMount: mount }),
  setActiveSessionId: (sessionId) => set({ activeSessionId: sessionId }),
  setSplitSessionId: (sessionId) => set({ splitSessionId: sessionId }),
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
      const splitSessionId = state.splitSessionId === sessionId ? null : state.splitSessionId
      let activeSessionId = state.activeSessionId
      if (activeSessionId === sessionId) {
        activeSessionId =
          next.find((session) => session.id !== splitSessionId)?.id ?? next[0]?.id ?? null
      }
      return {
        sessions: next,
        activeSessionId,
        splitSessionId: splitSessionId && next.length >= 2 ? splitSessionId : null
      }
    }),
  resetSessions: () =>
    set({
      sessions: [],
      activeSessionId: null,
      splitSessionId: null,
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
  dimensions?: TerminalCreateDimensions
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

export function resolveTerminalPanes(
  activeSessionId: string | null,
  splitSessionId: string | null,
  sessions: ReadonlyArray<TerminalSessionInfo>
): { top: string | null; bottom: string | null } {
  const splitExists =
    Boolean(splitSessionId) && sessions.some((session) => session.id === splitSessionId)
  if (!splitExists || !splitSessionId) {
    return { top: activeSessionId, bottom: null }
  }
  const top =
    activeSessionId && activeSessionId !== splitSessionId
      ? activeSessionId
      : (sessions.find((session) => session.id !== splitSessionId)?.id ?? null)
  return { top, bottom: splitSessionId }
}

/** Toggle IDE down-split: second click unsplits; first click opens a new bottom pane. */
export async function splitTerminalSessionDown(workspaceRoot: string): Promise<void> {
  const store = useTerminalSessionStore.getState()
  if (store.splitSessionId) {
    store.setSplitSessionId(null)
    return
  }
  const primaryId = store.activeSessionId
  const ok = await createTerminalSessionForWorkspace(workspaceRoot)
  if (!ok) return
  const next = useTerminalSessionStore.getState()
  const createdId = next.activeSessionId
  if (!createdId || !primaryId || createdId === primaryId) return
  next.setSplitSessionId(createdId)
  next.setActiveSessionId(primaryId)
}
