// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { AppSettingsV1 } from '@shared/app-settings'
import { CuaSettingsPanel } from './CuaSettingsPanel'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
globalThis.IS_REACT_ACT_ENVIRONMENT = true
let host: HTMLDivElement
let root: Root
let apps: { name: string; bundleId: string }[]
const runtimeRequest = vi.fn()
beforeEach(() => {
  apps = [{ name: 'Notes', bundleId: 'com.apple.Notes' }, { name: 'Chrome', bundleId: 'com.google.Chrome' }]
  runtimeRequest.mockReset().mockImplementation(async (path: string, _method: string, body?: string) => {
    if (path.endsWith('/revoke')) apps = apps.filter(app => app.bundleId !== JSON.parse(body!).app)
    return { ok: true, body: JSON.stringify(path.includes('/apps') ? { apps } : { permissions: [] }) }
  })
  Object.assign(window, { dsGui: { platform: 'darwin', runtimeRequest,
    getDeepseekConfigFile: vi.fn().mockResolvedValue({ content: '[cua]\nenabled = true\n' }) } })
  host = document.createElement('div')
  root = createRoot(host)
})
afterEach(async () => { await act(async () => root.unmount()) })
const render = async (form = {}) => act(async () => root.render(createElement(CuaSettingsPanel, {
  form: form as AppSettingsV1, onUpdate: vi.fn()
})))
const button = (label: string) => [...host.querySelectorAll('button')].find(b => b.textContent === label || b.getAttribute('title') === label)!

it('manages permanent apps even when computer control is disabled', async () => {
  await render({ cuaEnabled: false })
  expect(host.textContent).toContain('Notes')
  await act(async () => button('computerUseRevoke').click())
  expect(runtimeRequest).toHaveBeenCalledWith('/v1/cua/apps/revoke', 'POST', '{"app":"com.apple.Notes"}')
  expect(host.textContent).not.toContain('Notes')
  expect(host.textContent).toContain('Chrome')
})

it('refreshes newly granted apps and recovers from a failed read', async () => {
  runtimeRequest.mockRejectedValueOnce(new Error('offline'))
  await render({ cuaEnabled: false })
  expect(host.textContent).toContain('computerUseAppsError')
  expect(host.textContent).not.toContain('computerUseApprovedAppsEmpty')
  await act(async () => button('computerUseRefresh').click())
  expect(host.textContent).toContain('Notes')
  apps = [...apps, { name: 'Zed', bundleId: 'dev.zed.Zed' }]
  expect(button('computerUseRefresh')).toBeUndefined()
  await act(async () => root.render(null))
  await render({ cuaEnabled: false })
  expect(host.textContent).toContain('Zed')
  expect(host.textContent).not.toContain('computerUseAppsError')
})

it('explains automatic access and rereads grants on returning to settings', async () => {
  await render({ cuaAutoAllowApps: true })
  expect(host.textContent).toContain('cuaAutoAllowAppsRevokeHint')
  await act(async () => root.render(null))
  apps = []
  await render({ cuaAutoAllowApps: false })
  expect(host.textContent).toContain('computerUseApprovedAppsEmpty')
  expect(host.textContent).not.toContain('Notes')
  expect(host.textContent).not.toContain('cuaAutoAllowAppsRevokeHint')
})

it('does not offer macOS app grants on Linux', async () => {
  window.dsGui.platform = 'linux'
  await render()
  expect(host.textContent).not.toContain('computerUseApprovedApps')
  expect(runtimeRequest).not.toHaveBeenCalled()
})

it('keeps the grant visible when revocation fails and locks actions while pending', async () => {
  await render({ cuaEnabled: false })
  let reject!: (reason: Error) => void
  runtimeRequest.mockImplementationOnce(() => new Promise((_resolve, fail) => { reject = fail }))
  await act(async () => button('computerUseRevoke').click())
  expect(button('computerUseRefresh')).toBeUndefined()
  expect(button('computerUseRevoke').disabled).toBe(true)
  await act(async () => reject(new Error('authentication cancelled')))
  expect(host.textContent).toContain('Notes')
  expect(host.textContent).toContain('computerUseAppsError')
  expect(button('computerUseRevoke').disabled).toBe(false)
})

it('searches installed apps and adds only after the runtime confirms authorization', async () => {
  const baseRequest = runtimeRequest.getMockImplementation()!
  const music = { name: '汽水音乐', bundleId: 'com.soda.music', icon: 'data:image/png;base64,AA==' }
  runtimeRequest.mockImplementation(async (path, method, body) => {
    if (path.endsWith('/available')) return { ok: true, body: JSON.stringify({ apps: [music, { name: 'Terminal', bundleId: 'com.apple.Terminal', blocked: true }] }) }
    return baseRequest(path, method, body)
  })
  await render({ cuaEnabled: false })
  await act(async () => button('computerUseAddApp').click())
  expect(button('computerUseAppBlocked').disabled).toBe(true)
  expect(host.querySelector('img')?.getAttribute('src')).toBe(music.icon)
  const input = host.querySelector('input[type="search"]') as HTMLInputElement
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, '汽水')
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
  expect(host.textContent).not.toContain('Terminal')
  let complete!: (result: unknown) => void
  runtimeRequest.mockImplementationOnce(() => new Promise(resolve => { complete = resolve }))
  const allow = button('computerUseAlwaysAllow')
  await act(async () => { allow.click(); allow.click() })
  expect(runtimeRequest.mock.calls.filter(([path]) => path.endsWith('/allow'))).toHaveLength(1)
  expect(host.textContent).toContain('computerUseOwnerAuth')
  expect(button('computerUseUpdating').disabled).toBe(true)
  expect(host.querySelector('[title="computerUseRevoke"][aria-label*="汽水"]')).toBeNull()
  await act(async () => complete({ ok: true, body: JSON.stringify({ apps: [...apps, music] }) }))
  expect(host.querySelector('[title="computerUseRevoke"][aria-label*="汽水"]')).not.toBeNull()
})
