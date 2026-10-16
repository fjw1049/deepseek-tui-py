// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from 'vitest'
import { normalizeAppSettings, type AppSettingsV1 } from '@shared/app-settings'
import { cacheSettingsSnapshot, getSettingsSnapshot, loadSettingsSnapshot } from './settings-snapshot'

const settings = (theme: 'dark' | 'light') => normalizeAppSettings({ theme, deepseek: { apiKey: 'test', port: 7878 } } as AppSettingsV1)
afterEach(() => vi.unstubAllGlobals())

it('retains a successful startup read in memory and refreshes it on the next read', async () => {
  const getSettings = vi.fn().mockResolvedValueOnce(settings('dark')).mockResolvedValueOnce(settings('light'))
  vi.stubGlobal('dsGui', { getSettings })
  expect(getSettingsSnapshot()).toBeNull()
  await loadSettingsSnapshot()
  expect(getSettingsSnapshot()?.theme).toBe('dark')
  await loadSettingsSnapshot()
  expect(getSettingsSnapshot()?.theme).toBe('light')
  expect(getSettings).toHaveBeenCalledTimes(2)
})

it('does not let a read started before a save overwrite the saved configuration', async () => {
  let finish!: (value: AppSettingsV1) => void
  vi.stubGlobal('dsGui', { getSettings: () => new Promise<AppSettingsV1>(resolve => { finish = resolve }) })
  cacheSettingsSnapshot(settings('dark'))
  const pending = loadSettingsSnapshot()
  cacheSettingsSnapshot(settings('light'))
  finish(settings('dark'))
  expect((await pending).theme).toBe('light')
  expect(getSettingsSnapshot()?.theme).toBe('light')
})

it('preserves the last successful value on failure and isolates bridge sessions', async () => {
  vi.stubGlobal('dsGui', { getSettings: vi.fn().mockRejectedValue(new Error('read failed')) })
  cacheSettingsSnapshot(settings('dark'))
  await expect(loadSettingsSnapshot()).rejects.toThrow('read failed')
  expect(getSettingsSnapshot()?.theme).toBe('dark')
  vi.stubGlobal('dsGui', { getSettings: vi.fn() })
  expect(getSettingsSnapshot()).toBeNull()
})
