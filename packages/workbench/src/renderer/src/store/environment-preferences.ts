import { create } from 'zustand'
import { normalizeWorkspaceRoot } from '../lib/workspace-path'

export type ThreadEnvMode = 'local' | 'worktree'

const PREFIX = 'deepseekgui.envMode.'

function read(workspaceRoot: string): ThreadEnvMode | null {
  try {
    const value = window.localStorage.getItem(PREFIX + workspaceRoot)
    return value === 'worktree' || value === 'local' ? value : null
  } catch {
    return null
  }
}

function persist(workspaceRoot: string, mode: ThreadEnvMode): void {
  try {
    window.localStorage.setItem(PREFIX + workspaceRoot, mode)
  } catch {
    // Preference still works for the session without storage.
  }
}

/**
 * Remembered Local/Worktree choice per project workspace. Applies to threads
 * created from that workspace before a thread exists; once a thread runs a
 * turn its env mode is locked server-side.
 */
export const useEnvironmentPreferences = create<{
  modeByWorkspace: Record<string, ThreadEnvMode>
  setEnvMode: (workspaceRoot: string, mode: ThreadEnvMode) => void
}>((set) => ({
  modeByWorkspace: {},
  setEnvMode: (workspaceRoot, mode) => {
    const key = normalizeWorkspaceRoot(workspaceRoot)
    if (!key) return
    persist(key, mode)
    set((state) =>
      state.modeByWorkspace[key] === mode
        ? state
        : { modeByWorkspace: { ...state.modeByWorkspace, [key]: mode } }
    )
  }
}))

/** Default Local; falls back to the last choice remembered for this workspace. */
export function resolveWorkspaceEnvMode(
  modeByWorkspace: Record<string, ThreadEnvMode>,
  workspaceRoot: string | null | undefined
): ThreadEnvMode {
  const key = normalizeWorkspaceRoot(workspaceRoot ?? '')
  return (key && modeByWorkspace[key]) || 'local'
}
