// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { AppSettingsV1 } from '@shared/app-settings'
import { CuaSettingsPanel } from './CuaSettingsPanel'

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, string>) => options ? `${key}:${options.state}` : key
  })
}))

globalThis.IS_REACT_ACT_ENVIRONMENT = true
const getDeepseekConfigFile = vi.fn()
const runtimeRequest = vi.fn()
const onUpdate = vi.fn()
let host: HTMLDivElement
let root: Root

beforeEach(() => {
  vi.clearAllMocks()
  runtimeRequest.mockResolvedValue({ ok: true, body: '{"permissions": []}' })
  Object.assign(window, { dsGui: { platform: 'darwin', getDeepseekConfigFile, runtimeRequest } })
  host = document.createElement('div')
  root = createRoot(host)
})
afterEach(async () => { await act(async () => root.unmount()) })

async function render(form: Partial<AppSettingsV1>): Promise<HTMLButtonElement[]> {
  await act(async () => root.render(createElement(CuaSettingsPanel, { form: form as AppSettingsV1, onUpdate })))
  return [...host.querySelectorAll<HTMLButtonElement>('[role="switch"]')]
}

it('shows the value inherited from config.toml and lets the user explicitly disable it', async () => {
  getDeepseekConfigFile.mockResolvedValue({ content: '[cua]\nenabled = true\n' })
  const [enabled, , chrome] = await render({})
  expect(enabled!.getAttribute('aria-checked')).toBe('true')
  // An absent switch is off in the runtime.
  expect(chrome!.getAttribute('aria-checked')).toBe('false')
  expect(chrome!.disabled).toBe(false)
  await act(async () => {
    enabled!.click()
  })
  expect(onUpdate).toHaveBeenCalledWith({ cuaEnabled: false })
  const [, , chromeAfter] = await render({ cuaEnabled: false })
  expect(chromeAfter!.disabled).toBe(true)
})

it('disables Chrome while computer use is inherited as off', async () => {
  getDeepseekConfigFile.mockResolvedValue({ content: 'api_key = "x"\n' })
  const [enabled, , chrome] = await render({})
  expect(enabled!.getAttribute('aria-checked')).toBe('false')
  expect(chrome!.disabled).toBe(true)
})

it('says when the inherited value could not be read', async () => {
  getDeepseekConfigFile.mockRejectedValue(new Error('denied'))
  const [enabled, , chrome] = await render({})
  expect(host.textContent).toContain('cuaInheritedUnknown')
  expect(enabled!.disabled).toBe(true)
  expect(chrome!.disabled).toBe(true)
})

it('explains instead of offering controls on unsupported platforms', async () => {
  Object.assign(window, { dsGui: { platform: 'win32', getDeepseekConfigFile } })
  expect(await render({})).toHaveLength(0)
  expect(host.textContent).toContain('cuaUnsupported')
  expect(getDeepseekConfigFile).not.toHaveBeenCalled()
})

it('lists the macOS permissions the runtime needs and opens the matching pane', async () => {
  getDeepseekConfigFile.mockResolvedValue({ content: '[cua]\nenabled = true\n' })
  runtimeRequest.mockResolvedValue({ ok: true, body: JSON.stringify({ permissions: [
    { id: 'accessibility', name: 'ChatGPT Computer Use', path: '/x.app' },
    { id: 'screen', name: 'ChatGPT', path: '/y.app' }
  ] }) })
  await render({})
  const buttons = [...host.querySelectorAll<HTMLButtonElement>('button:not([role="switch"])')]
  expect(host.textContent).toContain('cuaPermissionAccessibility')
  expect(host.textContent).toContain('cuaPermissionScreen')
  await act(async () => buttons[1]!.click())
  expect(runtimeRequest).toHaveBeenLastCalledWith('/v1/cua/permissions/open', 'POST', '{"id":"screen"}')
  // Turned off: no permission guidance.
  runtimeRequest.mockClear()
  await render({ cuaEnabled: false })
  expect(host.querySelectorAll<HTMLButtonElement>('button:not([role="switch"])')).toHaveLength(0)
})

it('keeps switches in sync with updated settings and writes only the selected field', async () => {
  getDeepseekConfigFile.mockResolvedValue({ content: '[cua]\nenabled = true\n' })
  const [, preview] = await render({ cuaWindowPreview: false })
  expect(preview!.getAttribute('aria-checked')).toBe('false')
  await act(async () => preview!.click())
  expect(onUpdate).toHaveBeenCalledWith({ cuaWindowPreview: true })
  const [, updated] = await render({ cuaWindowPreview: true })
  expect(updated!.getAttribute('aria-checked')).toBe('true')
})

it('keeps the permission rows available when opening settings fails and allows retry', async () => {
  getDeepseekConfigFile.mockResolvedValue({ content: '[cua]\nenabled = true\n' })
  runtimeRequest.mockResolvedValueOnce({ ok: true, body: JSON.stringify({ permissions: [
    { id: 'screen', name: 'ChatGPT', path: '/y.app' }
  ] }) })
  await render({})
  expect(host.textContent).toContain('cuaSystemPermissions')
  expect(host.textContent).toContain('cuaPermissionRead')
  const button = host.querySelector<HTMLButtonElement>('button:not([role="switch"])')!
  runtimeRequest.mockRejectedValueOnce(new Error('unavailable'))
  await act(async () => button.click())
  expect(host.querySelector('[role="alert"]')?.textContent).toBe('cuaPermissionOpenFailed')
  expect(button.disabled).toBe(false)
  await act(async () => button.click())
  expect(host.querySelector('[role="alert"]')).toBeNull()
})

it('shows the permission section immediately while config and permission requests are pending', async () => {
  let resolveConfig!: (value: { content: string }) => void
  let resolvePermissions!: (value: { ok: boolean; body: string }) => void
  getDeepseekConfigFile.mockReturnValue(new Promise(resolve => { resolveConfig = resolve }))
  runtimeRequest.mockReturnValueOnce(new Promise(resolve => { resolvePermissions = resolve }))
  await render({})
  expect(runtimeRequest).toHaveBeenCalledWith('/v1/cua/permissions', 'GET')
  expect(host.textContent).toContain('cuaSystemPermissions')
  expect(host.textContent).toContain('cuaPermissionControl')
  expect(host.textContent).toContain('cuaPermissionRead')
  expect(host.textContent).toContain('cuaPermissionsLoading')
  const section = host.querySelectorAll('section')[1]
  await act(async () => {
    resolveConfig({ content: '[cua]\nenabled = true\n' })
    resolvePermissions({ ok: true, body: JSON.stringify({ permissions: [
      { id: 'screen', name: 'ChatGPT', path: '/y.app' }
    ] }) })
  })
  expect(host.querySelectorAll('section')[1]).toBe(section)
  expect(host.textContent).not.toContain('cuaPermissionsLoading')
  expect(host.textContent).toContain('cuaPermissionScreen')
})

it('keeps the section visible on load failure and retries without leaving the page', async () => {
  getDeepseekConfigFile.mockResolvedValue({ content: '[cua]\nenabled = true\n' })
  runtimeRequest.mockRejectedValueOnce(new Error('offline'))
  await render({})
  expect(host.textContent).toContain('cuaSystemPermissions')
  expect(host.textContent).toContain('cuaPermissionsUnavailable')
  const retry = host.querySelector<HTMLButtonElement>('button:not([role="switch"])')!
  await act(async () => retry.click())
  expect(host.textContent).not.toContain('cuaPermissionsUnavailable')
  expect(host.textContent).toContain('cuaPermissionsEmpty')
  expect(runtimeRequest).toHaveBeenCalledTimes(2)
})

it('renders preloaded information on first entry and reuses it on subsequent visits', async () => {
  const { getCuaSettingsData, preloadCuaSettings } = await import('../../lib/cua-settings-data')
  getDeepseekConfigFile.mockResolvedValue({ content: '[cua]\nenabled = true\n' })
  runtimeRequest.mockResolvedValue({ ok: true, body: JSON.stringify({ permissions: [
    { id: 'screen', name: 'ChatGPT', path: '/y.app' }
  ] }) })
  preloadCuaSettings(true)
  const data = getCuaSettingsData()
  await Promise.all([data.config.load(), data.permissions.load()])
  await render({})
  expect(host.textContent).not.toContain('cuaPermissionsLoading')
  expect(host.textContent).toContain('cuaPermissionScreen')
  await act(async () => root.render(null))
  await render({})
  expect(host.textContent).not.toContain('cuaPermissionsLoading')
  expect(runtimeRequest).toHaveBeenCalledOnce()
  expect(getDeepseekConfigFile).toHaveBeenCalledOnce()
})

it('times out a stuck settings request without disabling the other permission', async () => {
  getDeepseekConfigFile.mockResolvedValue({ content: '[cua]\nenabled = true\n' })
  runtimeRequest.mockResolvedValueOnce({ ok: true, body: JSON.stringify({ permissions: [
    { id: 'accessibility', name: 'Helper', path: '/x.app' },
    { id: 'screen', name: 'ChatGPT', path: '/y.app' }
  ] }) })
  await render({})
  const [first, second] = [...host.querySelectorAll<HTMLButtonElement>('button:not([role="switch"])')]
  runtimeRequest.mockReturnValueOnce(new Promise(() => {}))
  vi.useFakeTimers()
  try {
    await act(async () => first.click())
    expect(first.disabled).toBe(true)
    expect(second.disabled).toBe(false)
    await act(async () => vi.advanceTimersByTimeAsync(10_000))
    expect(first.disabled).toBe(false)
    expect(host.textContent).not.toContain('cuaPermissionOpening')
    expect(host.querySelector('[role="alert"]')?.textContent).toBe('cuaPermissionOpenFailed')
  } finally { vi.useRealTimers() }
})
