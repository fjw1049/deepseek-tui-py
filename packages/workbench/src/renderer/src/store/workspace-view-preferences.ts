import { create } from 'zustand'

const PREFIX = 'deepseekgui.workspaceView.'
function read(key: string): boolean | null {
  try {
    const value = window.localStorage.getItem(PREFIX + key)
    return value === 'true' ? true : value === 'false' ? false : null
  } catch { return null }
}
function persist(key: string, value: boolean): void {
  try { window.localStorage.setItem(PREFIX + key, String(value)) } catch { /* Session preference still works. */ }
}

export const useWorkspaceViewPreferences = create<{
  showAllFiles: boolean
  wrapLines: boolean | null
  setShowAllFiles: (value: boolean) => void
  setWrapLines: (value: boolean) => void
}>((set) => ({
  showAllFiles: read('showAllFiles') ?? false,
  wrapLines: read('wrapLines'),
  setShowAllFiles: (value) => { set({ showAllFiles: value }); persist('showAllFiles', value) },
  setWrapLines: (value) => { set({ wrapLines: value }); persist('wrapLines', value) }
}))
