// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { beforeEach, afterEach, expect, it, vi } from 'vitest'
import { CuaPreviewPermission } from './CuaPreviewPermission'
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string, args?: { name: string }) => args ? `${key}:${args.name}` : key }) }))
globalThis.IS_REACT_ACT_ENVIRONMENT = true
let root: ReturnType<typeof createRoot>
let host: HTMLDivElement
const status = vi.fn()
const request = vi.fn()
beforeEach(() => {
  status.mockReset().mockResolvedValue({ status: 'denied', appName: 'Electron' })
  request.mockReset().mockResolvedValue(undefined)
  Object.assign(window, { dsGui: { getCuaScreenPermission: status, openScreenCaptureSettings: request } })
  host = document.createElement('div')
  root = createRoot(host)
})
afterEach(async () => { await act(async () => root.unmount()) })
it('names the preview app and never treats opening settings as a grant', async () => {
  await act(async () => root.render(createElement(CuaPreviewPermission)))
  expect(host.textContent).toContain('cuaPermissionScreen:Electron')
  await act(async () => host.querySelector('button')!.click())
  expect(request).toHaveBeenCalledOnce()
  expect(host.textContent).not.toContain('cuaPreviewPermissionGranted')
  status.mockResolvedValue({ status: 'granted', appName: 'Electron' })
  await act(async () => window.dispatchEvent(new Event('focus')))
  expect(host.textContent).toContain('cuaPreviewPermissionGranted')
  expect(host.querySelector('button')).toBeNull()
})
it('keeps the entry visible and retryable when native capture fails', async () => {
  request.mockRejectedValue(new Error('Failed to get sources'))
  await act(async () => root.render(createElement(CuaPreviewPermission)))
  await act(async () => host.querySelector('button')!.click())
  expect(host.querySelector('[role="alert"]')).not.toBeNull()
  expect(host.querySelector('button')!.disabled).toBe(false)
  expect(host.textContent).toContain('cuaPreviewPermissionTitle')
})
