import { afterEach, expect, it, vi } from 'vitest'

afterEach(() => { vi.unstubAllGlobals(); vi.resetModules() })
it('persists both preferences across store reloads', async () => {
  const values = new Map<string, string>()
  vi.stubGlobal('window', { localStorage: {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value)
  } })
  const { useWorkspaceViewPreferences: store } = await import('./workspace-view-preferences')
  expect(store.getState().showAllFiles).toBe(false)
  expect(store.getState().wrapLines).toBe(null)
  store.getState().setShowAllFiles(true)
  store.getState().setWrapLines(true)
  vi.resetModules()
  const reloaded = (await import('./workspace-view-preferences')).useWorkspaceViewPreferences
  expect(reloaded.getState().showAllFiles).toBe(true)
  expect(reloaded.getState().wrapLines).toBe(true)
})
it('keeps session preferences usable without local storage', async () => {
  vi.stubGlobal('window', { get localStorage() { throw new Error('blocked') } })
  const { useWorkspaceViewPreferences: store } = await import('./workspace-view-preferences')
  store.getState().setWrapLines(false)
  expect(store.getState().wrapLines).toBe(false)
})
