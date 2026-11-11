// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { AutomationPermissions } from './AutomationPermissions'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))

it('never grants on render; only the user checkbox issues a separate permission request', async () => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  const request = vi.fn().mockResolvedValueOnce({ ok: true, body: '{"allow_browser":false}' })
    .mockResolvedValueOnce({ ok: true, body: '{"allow_browser":true}' })
    .mockResolvedValueOnce({ ok: false, body: '{"message":"cannot save"}' })
  Object.defineProperty(window, 'dsGui', { configurable: true, value: { runtimeRequest: request } })
  const container = document.createElement('div')
  const root = createRoot(container)
  try {
    await act(async () => root.render(createElement(AutomationPermissions, { automationId: 'one' })))
    const checkbox = container.querySelector<HTMLInputElement>('input')!
    expect(checkbox.checked).toBe(false)
    expect(request.mock.calls).toEqual([['/v1/automations/one/permissions', 'GET']])
    await act(async () => checkbox.click())
    expect(request).toHaveBeenLastCalledWith('/v1/automations/one/permissions', 'PUT', '{"allow_browser":true}')
    expect(checkbox.checked).toBe(true)
    await act(async () => checkbox.click())
    expect(checkbox.checked).toBe(true) // never claim a failed revocation succeeded
    expect(container.querySelector('[role="alert"]')?.textContent).toBe('cannot save')
  } finally {
    await act(async () => root.unmount())
    vi.unstubAllGlobals()
  }
})
