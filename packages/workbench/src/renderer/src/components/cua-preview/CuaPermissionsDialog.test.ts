// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { CuaPermissionsDialog } from './CuaPermissionsDialog'
const t = (key: string, args?: { app: string }) => args ? `${key}:${args.app}` : key
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t }) }))
globalThis.IS_REACT_ACT_ENVIRONMENT = true
let root: ReturnType<typeof createRoot>
let host: HTMLDivElement
let screen: ReturnType<typeof vi.fn>
let open: ReturnType<typeof vi.fn>
let request: ReturnType<typeof vi.fn>
beforeEach(() => {
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
  screen = vi.fn(async () => ({ status: 'denied', appName: 'Electron' }))
  open = vi.fn(async () => {})
  request = vi.fn(async () => ({ ok: true, body: JSON.stringify({ permissions: [
    { id: 'accessibility', name: 'Computer Use Helper', path: '/Applications/Helper.app' }
  ] }) }))
  Object.defineProperty(window, 'dsGui', { configurable: true, value: {
    getCuaScreenPermission: screen, openScreenCaptureSettings: open, runtimeRequest: request
  } })
})
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks() })
const render = () => act(async () => root.render(createElement(CuaPermissionsDialog, { onClose: vi.fn() })))
it('names the actual app and opens settings without claiming permission was granted', async () => {
  await render()
  expect(document.body.textContent).toContain('cuaPermissionApp:Electron')
  expect(document.body.textContent).toContain('Computer Use Helper')
  const buttons = [...document.querySelectorAll('button')].filter(b => b.textContent === 'cuaPermissionOpen')
  await act(async () => buttons[0].click())
  expect(open).toHaveBeenCalledOnce()
  expect(document.body.textContent).toContain('cuaPermissionNeeded')
  const runtimeButton = [...document.querySelectorAll('button')].find(b => b.textContent === 'cuaPermissionView')!
  await act(async () => runtimeButton.click())
  expect(request).toHaveBeenCalledWith('/v1/cua/permissions/open', 'POST', '{"id":"accessibility","path":"/Applications/Helper.app"}')
})
it('checks on return and refreshes preview only after a real grant', async () => {
  const recheck = vi.fn(); window.addEventListener('cua-permission-recheck', recheck)
  try {
    await render()
    expect(recheck).not.toHaveBeenCalled()
    screen.mockResolvedValue({ status: 'granted', appName: 'Electron' })
    await act(async () => window.dispatchEvent(new Event('focus')))
    expect(document.body.textContent).toContain('cuaPermissionGranted')
    expect(recheck).toHaveBeenCalledOnce()
  } finally { window.removeEventListener('cua-permission-recheck', recheck) }
})
it('shows an actionable failure when opening settings fails', async () => {
  open.mockRejectedValue(new Error('cannot open'))
  await render()
  const button = [...document.querySelectorAll('button')].find(b => b.textContent === 'cuaPermissionOpen')!
  await act(async () => button.click())
  expect(document.querySelector('[role="alert"]')!.textContent).toBe('cuaPermissionError')
})

it('explains that an older desktop window must reopen instead of crashing', async () => {
  Object.defineProperty(window, 'dsGui', { configurable: true, value: {
    openScreenCaptureSettings: open, runtimeRequest: request
  } })
  await render()
  expect(document.querySelector('[role="alert"]')!.textContent).toBe('cuaPermissionRestart')
})

it('rechecks failed runtime permissions and explains each separate capability', async () => {
  request.mockResolvedValueOnce({ ok: false, body: '' })
  await render()
  expect(document.body.textContent).toContain('cuaPermissionPreviewPurpose')
  expect(document.body.textContent).toContain('cuaPermissionListError')
  const check = [...document.querySelectorAll('button')].find(b => b.textContent === 'cuaPermissionCheck')!
  await act(async () => check.click())
  expect(document.body.textContent).not.toContain('cuaPermissionListError')
  expect(document.body.textContent).toContain('cuaPermissionAccessibilityPurpose')
  expect(document.body.textContent).toContain('cuaPermissionApp:Computer Use Helper')
})

it('rechecks a grant immediately after the native request finishes', async () => {
  await render()
  open.mockImplementation(async () => { screen.mockResolvedValue({ status: 'granted', appName: 'Electron' }) })
  const button = [...document.querySelectorAll('button')].find(b => b.textContent === 'cuaPermissionOpen')!
  await act(async () => button.click())
  expect(document.body.textContent).toContain('cuaPermissionGranted')
  expect(document.body.textContent).not.toContain('cuaPermissionMissingEntry')
})
