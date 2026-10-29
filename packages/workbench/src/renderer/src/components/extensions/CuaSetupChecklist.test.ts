// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import { CuaSetupChecklist, type CuaSetupState } from './CuaSetupChecklist'
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('../../lib/settings-snapshot', () => ({ cacheSettingsSnapshot: vi.fn() }))

const links = { chatgpt: 'https://chatgpt.com/download/', guide: 'https://example.test/guide' }
const state = (patch: Partial<CuaSetupState> = {}): CuaSetupState => ({
  target: 'darwin-arm64', chatgpt: true, busy: false, chromeConnector: 'missing', links,
  lcu: { installed: false, version: null, pinned: '0.11.6' }, ...patch
})
const ok = (body: unknown) => ({ ok: true, body: JSON.stringify(body) })
let root: ReturnType<typeof createRoot> | null = null

afterEach(async () => { await act(async () => root?.unmount()); root = null })

async function render(runtimeRequest: ReturnType<typeof vi.fn>, extra: Record<string, unknown> = {}) {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  const dsGui = { platform: 'darwin', runtimeRequest, openExternal: vi.fn(), openChromeSetupPage: vi.fn(),
    setSettings: vi.fn().mockResolvedValue({ cuaChrome: true }), ...extra }
  Object.assign(window, { dsGui })
  const onChanged = vi.fn()
  const host = document.createElement('div')
  root = createRoot(host)
  await act(async () => root!.render(createElement(CuaSetupChecklist, { onChanged, onOpenPermissions: vi.fn() })))
  const button = (label: string) => [...host.querySelectorAll('button')].find(b => b.textContent === label)
  return { host, dsGui, onChanged, button }
}

it('installs the pinned component with one click, then shows its version', async () => {
  let installed = false
  const runtimeRequest = vi.fn(async (path: string, method: string) => {
    if (path === '/v1/cua/setup/lcu' && method === 'POST') { installed = true; return ok({ ok: true, version: '0.11.6' }) }
    return ok(state({ lcu: { installed, version: installed ? '0.11.6' : null, pinned: '0.11.6' } }))
  })
  const { host, onChanged, button } = await render(runtimeRequest)
  expect(host.textContent).toContain('cuaSetupLcuMissing')
  await act(async () => button('cuaSetupInstall')!.click())
  expect(runtimeRequest).toHaveBeenCalledWith('/v1/cua/setup/lcu', 'POST')
  expect(host.textContent).toContain('cuaSetupLcuReady')
  expect(button('cuaSetupInstall')).toBeUndefined()
  expect(onChanged).toHaveBeenCalled()
})

it('sends the user to ChatGPT first, and to the guide where one click is unsupported', async () => {
  const missing = await render(vi.fn(async () => ok(state({ chatgpt: false }))))
  expect(missing.button('cuaSetupInstall')).toBeUndefined()
  await act(async () => missing.button('cuaSetupDownload')!.click())
  expect(missing.dsGui.openExternal).toHaveBeenCalledWith(links.chatgpt)
  await act(async () => root!.unmount())

  const linux = await render(vi.fn(async () => ok(state({ target: null }))))
  expect(linux.button('cuaSetupInstall')).toBeUndefined()
  await act(async () => linux.button('cuaSetupGuide')!.click())
  expect(linux.dsGui.openExternal).toHaveBeenCalledWith(links.guide)
})

it('shows why an installation failed', async () => {
  const runtimeRequest = vi.fn(async (path: string) => path === '/v1/cua/setup/lcu'
    ? { ok: false, body: JSON.stringify({ detail: { message: 'Integrity check failed', error: 'cua_setup_failed' } }) }
    : ok(state()))
  const { host, button } = await render(runtimeRequest)
  await act(async () => button('cuaSetupInstall')!.click())
  expect(host.querySelector('[role="alert"]')!.textContent).toBe('Integrity check failed')
})

it('connects Chrome, explains a missing extension, and enables Chrome once connected', async () => {
  let connector: CuaSetupState['chromeConnector'] = 'missing'
  let connected = false
  const runtimeRequest = vi.fn(async (path: string) => {
    if (path === '/v1/cua/setup/chrome') { connector = 'installed'; return ok({ ok: true }) }
    if (path === '/v1/cua/setup/chrome/verify') return ok({ connected, reason: connected ? null : 'extension' })
    return ok(state({ chromeConnector: connector, lcu: { installed: true, version: '0.11.6', pinned: '0.11.6' } }))
  })
  const { host, dsGui, button } = await render(runtimeRequest)
  expect(button('cuaSetupVerify')!.disabled).toBe(true)
  await act(async () => button('cuaSetupConnect')!.click())
  expect(button('cuaSetupConnect')).toBeUndefined()
  await act(async () => button('cuaSetupVerify')!.click())
  expect(host.textContent).toContain('cuaSetupChromeNoExtension')
  await act(async () => button('cuaSetupOpenStore')!.click())
  await act(async () => button('cuaSetupOpenExtension')!.click())
  expect(dsGui.openChromeSetupPage.mock.calls).toEqual([['store'], ['extension']])
  connected = true
  await act(async () => button('cuaSetupVerify')!.click())
  expect(host.textContent).toContain('cuaSetupChromeConnected')
  await act(async () => button('cuaSetupEnableChrome')!.click())
  expect(dsGui.setSettings).toHaveBeenCalledWith({ cuaChrome: true })
  expect(button('cuaSetupChromeEnabled')!.disabled).toBe(true)
})
