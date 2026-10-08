// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { BrowserSessionSettings } from './BrowserSessionSettings'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('./DevBrowserPanel', () => ({ DevBrowserPanel: () => null }))
vi.mock('../store/chat-store', () => ({ useChatStore: () => null }))

it('checks the environment, saves profile preferences, previews and executes a workflow', async () => {
  const request = vi.fn(async (path: string, method: string, raw?: string) => {
    let body: unknown = {}
    if (path.endsWith('/preferences')) body = { persistent: false }
    if (path.endsWith('/environment')) body = { ready: true, python: '3.12' }
    if (path.endsWith('/workflows') && method === 'GET') body = { items: [{ id: 'rec_test', steps: 2, status: 'stopped' }] }
    if (raw && JSON.parse(raw).action === 'preview') body = { inputs: [], steps: [{ id: '1', kind: 'click', description: 'Save settings' }] }
    return { ok: true, status: 200, body: JSON.stringify(body) }
  })
  Object.defineProperty(window, 'dsGui', { configurable: true, value: { runtimeRequest: request } })
  const container = document.createElement('div')
  const root = createRoot(container)
  const click = async (label: string): Promise<void> => {
    const button = [...container.querySelectorAll('button')].find((b) => b.textContent?.includes(label))!
    expect(button.disabled).toBe(false)
    await act(async () => button.click())
  }
  try {
    await act(async () => root.render(createElement(BrowserSessionSettings, { threadId: 'one', active: false, userControls: false, recording: false })))
    await click('browserCheckEnvironment')
    expect(container.textContent).toContain('browserEnvironmentReady')
    await act(async () => container.querySelector<HTMLInputElement>('input[type=checkbox]')!.click())
    expect(request).toHaveBeenCalledWith('/v1/threads/one/browser/preferences', 'POST', '{"persistent":true}')
    await act(async () => root.render(createElement(BrowserSessionSettings, { threadId: 'one', active: true, userControls: true, recording: false })))
    expect(container.querySelector<HTMLInputElement>('input[type=checkbox]')!.disabled).toBe(true)
    await click('browserWorkflowStart')
    expect(request).toHaveBeenCalledWith('/v1/threads/one/browser/workflows', 'POST', '{"action":"start"}')
    await click('rec_test')
    expect(container.textContent).toContain('Save settings')
    await click('browserWorkflowReplay')
    expect(request).toHaveBeenCalledWith('/v1/threads/one/browser/workflows', 'POST', '{"action":"replay","recording_id":"rec_test","inputs":{}}')
  } finally {
    await act(async () => root.unmount())
  }
})
