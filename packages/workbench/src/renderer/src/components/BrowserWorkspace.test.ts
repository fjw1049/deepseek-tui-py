// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { AgentBrowserPanel, BrowserWorkspace } from './BrowserWorkspace'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('./DevBrowserPanel', () => ({ DevBrowserPanel: () => null }))

it('uses the displayed conversation and switches isolated browser sessions', async () => {
  const request = vi.fn(async (path: string) => ({ ok: true, status: 200, body: JSON.stringify(
    path.endsWith('/workflows') ? { items: [] } : { active: false, owner: 'agent', log: [], artifacts: [] }
  ) }))
  Object.defineProperty(window, 'dsGui', { configurable: true, value: { runtimeRequest: request } })
  const container = document.createElement('div')
  const root = createRoot(container)
  try {
    await act(async () => root.render(createElement(BrowserWorkspace, { blocks: [], threadId: 'first' })))
    await act(async () => [...container.querySelectorAll('button')].find((b) => b.textContent === 'browserAgentWorkspace')!.click())
    expect(request).toHaveBeenCalledWith('/v1/threads/first/browser', 'GET', undefined)
    await act(async () => root.render(createElement(BrowserWorkspace, { blocks: [], threadId: 'second' })))
    expect(request).toHaveBeenCalledWith('/v1/threads/second/browser', 'GET', undefined)
    await act(async () => root.render(createElement(BrowserWorkspace, { blocks: [], threadId: null })))
    expect(container.textContent).toContain('browserNeedThread')
  } finally {
    await act(async () => root.unmount())
  }
})

it('runs a demo, takes control, ends the session and exposes evidence through the runtime bridge', async () => {
  let state = { active: false, owner: 'agent', recording: false, demo_status: 'idle',
    demo_step: 3, demo_total: 9, log: [], artifacts: [], error: null }
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
    expect(container.querySelector('progress')?.value).toBe(3)
    expect(container.querySelector('progress')?.max).toBe(9)
    await click('browserTakeControl')
    expect(container.textContent).toContain('browserUserControl')
    expect(container.textContent).toContain('browserDemoStopped')
    await click('browserEndSession')
    expect(container.textContent).toContain('browserIdle')
  } finally {
    await act(async () => root.unmount())
  }
})

it('syncs navigation without overwriting a draft on unchanged polls, previews video and exports', async () => {
  vi.useFakeTimers()
  let url = 'http://localhost/redirected'
  const reveal = vi.fn()
  const request = vi.fn(async (path: string) => {
    let body: unknown = { active: true, owner: 'user', url, recording: false,
      demo_status: 'passed', log: [], artifacts: [{ id: 'clip.webm', label: '连续视频' }] }
    if (path.endsWith('/frame')) body = { image: null }
    if (path.endsWith('/workflows')) body = { items: [] }
    if (path.endsWith('/artifacts/clip.webm')) body = { image: 'data:video/webm;base64,AA==' }
    if (path.endsWith('/export')) body = { path: '/tmp/evidence.zip' }
    return { ok: true, status: 200, body: JSON.stringify(body) }
  })
  Object.defineProperty(window, 'dsGui', { configurable: true, value: { runtimeRequest: request, showItemInFolder: reveal } })
  const container = document.createElement('div')
  const root = createRoot(container)
  try {
    await act(async () => root.render(createElement(AgentBrowserPanel, { threadId: 'one' })))
    const address = container.querySelector<HTMLInputElement>('[aria-label="browserAddressPlaceholder"]')!
    expect(address.value).toBe(url)
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(address, 'http://localhost/draft')
      address.dispatchEvent(new Event('input', { bubbles: true }))
      await vi.advanceTimersByTimeAsync(600)
    })
    expect(address.value).toBe('http://localhost/draft')
    url = 'http://localhost/redirected#next'
    await act(async () => { await vi.advanceTimersByTimeAsync(600) })
    expect(address.value).toBe(url)
    const buttons = [...container.querySelectorAll('button')]
    await act(async () => buttons.find((b) => b.textContent === '1. browserVideo')!.click())
    expect(container.querySelector('video')?.getAttribute('src')).toBe('data:video/webm;base64,AA==')
    await act(async () => buttons.find((b) => b.textContent === 'browserExportEvidence')!.click())
    expect(reveal).toHaveBeenCalledWith('/tmp/evidence.zip')
  } finally {
    await act(async () => root.unmount())
    vi.useRealTimers()
  }
})
