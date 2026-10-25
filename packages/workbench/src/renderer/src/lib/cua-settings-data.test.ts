// @vitest-environment happy-dom
import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import { getCuaSettingsData, preloadCuaSettings } from './cua-settings-data'

const config = vi.fn()
const request = vi.fn()
beforeEach(() => {
  config.mockReset().mockResolvedValue({ content: '[cua]\nenabled = true\n' })
  request.mockReset().mockResolvedValue({ ok: true, body: JSON.stringify({ permissions: [
    { id: 'screen', name: 'Helper', path: '/Helper.app' }
  ] }) })
  Object.assign(window, { dsGui: { platform: 'darwin', getDeepseekConfigFile: config, runtimeRequest: request } })
})
afterEach(() => vi.restoreAllMocks())

it('prepares configuration at startup and permissions when the runtime is ready', async () => {
  preloadCuaSettings(false)
  const data = getCuaSettingsData()
  await data.config.load()
  expect(config).toHaveBeenCalledOnce()
  expect(request).not.toHaveBeenCalled()
  preloadCuaSettings(true)
  await data.permissions.load()
  expect(data.config.getSnapshot().value?.enabled).toBe(true)
  expect(data.permissions.getSnapshot().value?.[0].name).toBe('Helper')
  expect(request).toHaveBeenCalledOnce()
  await Promise.all([data.config.load(), data.permissions.load()])
  expect(config).toHaveBeenCalledOnce()
  expect(request).toHaveBeenCalledOnce()
})

it('shares pending requests between startup and navigation', async () => {
  let finish!: (result: { ok: boolean; body: string }) => void
  request.mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
  preloadCuaSettings(true)
  const data = getCuaSettingsData()
  const first = data.permissions.load()
  const second = data.permissions.load()
  expect(first).toBe(second)
  await Promise.resolve()
  expect(request).toHaveBeenCalledOnce()
  finish({ ok: true, body: '{"permissions": []}' })
  await first
})

it('keeps visible data during refresh and informs mounted pages of new results', async () => {
  const data = getCuaSettingsData()
  await data.permissions.load()
  const listener = vi.fn()
  const unsubscribe = data.permissions.subscribe(listener)
  request.mockResolvedValueOnce({ ok: true, body: '{"permissions": []}' })
  preloadCuaSettings(true)
  expect(data.permissions.getSnapshot().value?.[0].name).toBe('Helper')
  await data.permissions.load()
  expect(data.permissions.getSnapshot().value).toEqual([])
  expect(listener).toHaveBeenCalled()
  unsubscribe()
})

it('refreshes expired data instead of retaining component identities indefinitely', async () => {
  const now = vi.spyOn(Date, 'now').mockReturnValue(1000)
  const data = getCuaSettingsData()
  await data.permissions.load()
  now.mockReturnValue(62_000)
  await data.permissions.load()
  expect(request).toHaveBeenCalledTimes(2)
})

it('can recover from a failed startup request', async () => {
  request.mockRejectedValueOnce(new Error('offline'))
  preloadCuaSettings(true)
  const data = getCuaSettingsData()
  await data.permissions.load()
  expect(data.permissions.getSnapshot().failed).toBe(true)
  preloadCuaSettings(true)
  await data.permissions.load()
  expect(data.permissions.getSnapshot().failed).toBe(false)
  expect(data.permissions.getSnapshot().value?.[0].name).toBe('Helper')
})
