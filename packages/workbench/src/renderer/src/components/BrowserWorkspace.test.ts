// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { AgentBrowserPanel } from './BrowserWorkspace'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('./DevBrowserPanel', () => ({ DevBrowserPanel: () => null }))
vi.mock('../store/chat-store', () => ({ useChatStore: () => null }))

it('runs a demo, takes control, ends the session and exposes evidence through the runtime bridge', async () => {
  let state = { active: false, owner: 'agent', recording: false, demo_status: 'idle',
    log: [], artifacts: [], error: null }
  const request = vi.fn(async (path: string, _method: string, raw?: string) => {
    if (path.endsWith('/demo')) state = { ...state, active: true, demo_status: 'running' }
    if (path.endsWith('/control')) {
      const owner = JSON.parse(raw!).owner
      state = { ...state, owner, active: owner !== 'stopped', demo_status: 'stopped' }
    }
    return { ok: true, status: 200, body: JSON.stringify(state) }
  })
  Object.defineProperty(window, 'dsGui', { configurable: true, value: { runtimeRequest: request } })
  const container = document.createElement('div')
  const root = createRoot(container)
  const click = async (label: string): Promise<void> => {
    const button = [...container.querySelectorAll('button')].find((b) => b.textContent === label)!
    expect(button).toBeTruthy()
    await act(async () => button.click())
  }
  try {
    await act(async () => root.render(createElement(AgentBrowserPanel, { threadId: 'thr_demo' })))
    await click('browserRunDemo')
    expect(request).toHaveBeenCalledWith('/v1/threads/thr_demo/browser/demo', 'POST', '{}')
    expect(container.textContent).toContain('browserDemoRunning')
    await click('browserTakeControl')
    expect(container.textContent).toContain('browserUserControl')
    await click('browserEndSession')
    expect(container.textContent).toContain('browserIdle')
  } finally {
    await act(async () => root.unmount())
  }
})
