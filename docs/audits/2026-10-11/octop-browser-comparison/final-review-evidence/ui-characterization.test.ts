import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { AgentBrowserPanel } from '/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/BrowserWorkspace'
import { BrowserViewport } from '/Users/fjw/Desktop/deepseek-tui-py-main/packages/workbench/src/renderer/src/components/BrowserViewport'
globalThis.IS_REACT_ACT_ENVIRONMENT = true
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))

it('reproduces: an executed action is displayed as failure if view refresh fails', async () => {
  const state = { active: true, owner: 'user', generation: 2, url: 'https://example.test', image: 'data:image/jpeg;base64,AA==', tabs: [], log: [], artifacts: [] }
  let executed = 0
  const request = vi.fn(async (path: string) => {
    if (path.endsWith('/action')) { executed++; return { ok: true, status: 200, body: JSON.stringify({ success: true, receipt: { action_id: 'synthetic_action', execution: 'executed', effect: 'unchecked' }, content: 'reload dispatched' }) } }
    if (path.endsWith('/view') && executed) throw new Error('Screenshot temporarily unavailable')
    return { ok: true, status: 200, body: JSON.stringify(state) }
  })
  Object.defineProperty(window, 'dsGui', { configurable: true, value: { runtimeRequest: request } })
  const container = document.createElement('div'); const root = createRoot(container)
  try {
    await act(async () => root.render(createElement(AgentBrowserPanel, { threadId: 'one' })))
    await act(async () => container.querySelector<HTMLButtonElement>('[aria-label="browserReload"], [aria-label="Reload"]')!.click())
    expect(executed).toBe(1)
    expect(container.querySelector('[role="alert"]')!.textContent).toContain('Screenshot temporarily unavailable')
    expect(container.textContent).not.toContain('reload dispatched')
    // This passing characterization demonstrates the bug, not a correctness pass.
  } finally { await act(async () => root.unmount()) }
})

it('reproduces: transient disable followed by re-enable does not invalidate queued input', async () => {
  const container = document.createElement('div'); const root = createRoot(container)
  let finish!: (value: {}) => void
  const send = vi.fn(() => new Promise<{}>(resolve => { finish = resolve }))
  const base = { image: 'data:image/jpeg;base64,AA==', width: 1200, height: 760, label: 'Page', resizeEnabled: false, generation: 2, send, onError: vi.fn() }
  try {
    await act(async () => root.render(createElement(BrowserViewport, { ...base, enabled: true })))
    const field = container.querySelector('textarea')!
    await act(async () => {
      field.value = 'first'; field.dispatchEvent(new InputEvent('input', { bubbles: true }))
      field.value = 'queued before navigation'; field.dispatchEvent(new InputEvent('input', { bubbles: true }))
    })
    expect(send).toHaveBeenCalledTimes(1)
    await act(async () => root.render(createElement(BrowserViewport, { ...base, enabled: false })))
    await act(async () => root.render(createElement(BrowserViewport, { ...base, enabled: true })))
    await act(async () => finish({}))
    expect(send).toHaveBeenCalledTimes(2)
    expect(send).toHaveBeenLastCalledWith({ kind: 'text', text: 'queued before navigation', generation: 2 })
    // The real input endpoint checks owner/generation only, not tab/document identity.
  } finally { await act(async () => root.unmount()) }
})
