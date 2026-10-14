// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { AgentBrowserPanel, BrowserWorkspace } from './BrowserWorkspace'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
const resume = vi.hoisted(() => vi.fn(async () => true))
vi.mock('../store/chat-store', () => ({ useChatStore: { getState: () => ({ sendMessage: resume }) } }))

function mount(state = { active: true, owner: 'user', generation: 2, url: 'https://example.test', image: 'data:image/jpeg;base64,AA==', tabs: [{ tab_id: 'first', title: 'Example', url: 'https://example.test/', active: true }], log: [], artifacts: [] } as Record<string, unknown>) {
  const request = vi.fn(async (path: string, _method: string, raw?: string) => {
    if (path.endsWith('/control')) { const owner = JSON.parse(raw!).owner; state = { ...state, owner, active: owner !== 'stopped', generation: Number(state.generation) + 1 } }
    return { ok: true, status: 200, body: JSON.stringify(path.endsWith('/workflows') ? { items: [] } : path.endsWith('/input') ? { success: true } : state) }
  })
  Object.defineProperty(window, 'dsGui', { configurable: true, value: { openExternal: vi.fn(async () => {}), runtimeRequest: request, onDevBrowserOpenUrl: vi.fn(() => () => {}) } })
  const container = document.createElement('div'); document.body.append(container)
  const root = createRoot(container)
  const click = async (label: string): Promise<void> => { await act(async () => { const button = [...document.querySelectorAll('button')].find(b => !b.closest('.hidden') && (b.textContent === label || b.getAttribute('aria-label') === label)); expect(button).toBeTruthy(); button!.click() }) }
  return { root, container, request, click, close: async () => { await act(async () => root.unmount()); container.remove() } }
}

it('keeps the executed receipt when only the following view fails', async () => {
  const h = mount()
  let executed = 0
  h.request.mockImplementation(async (path: string) => {
    if (path.endsWith('/action')) {
      executed++
      return { ok: true, status: 200, body: JSON.stringify({ success: true, content: 'reload dispatched', receipt: { action_id: 'saved', execution: 'executed' } }) }
    }
    if (executed && path.endsWith('/view')) throw new Error('view temporarily unavailable')
    return { ok: true, status: 200, body: JSON.stringify({ active: true, owner: 'user', generation: 2, image: 'data:image/jpeg;base64,AA==', tabs: [], log: [], artifacts: [] }) }
  })
  try {
    await act(async () => h.root.render(createElement(AgentBrowserPanel, { threadId: 'one' })))
    vi.useFakeTimers()
    await h.click('browserReload')
    expect(executed).toBe(1)
    await act(async () => h.container.querySelector<HTMLButtonElement>('.ds-browser-status-trigger')!.click())
    expect(h.container.textContent).toContain('browserActionSentViewUnavailable')
    expect(h.container.querySelector('textarea')?.disabled).toBe(true)
    expect(h.container.querySelector('.ds-browser-feedback')?.parentElement?.className).toBe('ds-browser-content')
    await act(async () => vi.advanceTimersByTime(4000))
    expect(h.container.querySelector('.ds-browser-feedback')).toBeNull()
    expect(h.container.textContent).toContain('browserConnectionProblem')
  } finally { vi.useRealTimers(); await h.close() }
})

it('preserves an unknown HTTP action receipt for the user', async () => {
  const h = mount()
  const original = h.request.getMockImplementation()!
  h.request.mockImplementation(async (path, method, raw) => path.endsWith('/action') ? {
    ok: false, status: 409, body: JSON.stringify({ detail: { success: false, content: 'inspect before retrying', receipt: { action_id: 'unknown', execution: 'unknown' } } })
  } : original(path, method, raw))
  try {
    await act(async () => h.root.render(createElement(AgentBrowserPanel, { threadId: 'one' })))
    await h.click('browserReload')
    await act(async () => h.container.querySelector<HTMLButtonElement>('.ds-browser-status-trigger')!.click())
    expect(h.container.textContent).toContain('browserOutcomeUnknown')
  } finally { await h.close() }
})

it('rejects an older view response within the same control generation', async () => {
  vi.useFakeTimers()
  const h = mount()
  let first: ((value: { ok: boolean; status: number; body: string }) => void) | undefined
  let views = 0
  const state = { active: true, owner: 'user', generation: 2, tabs: [], log: [], artifacts: [], image: 'data:image/jpeg;base64,AA==' }
  h.request.mockImplementation(async (path) => {
    if (path.endsWith('/view') && ++views === 2) return await new Promise(resolve => { first = resolve })
    return { ok: true, status: 200, body: JSON.stringify({ ...state, view_sequence: 2, url: 'https://new.example' }) }
  })
  try {
    await act(async () => h.root.render(createElement(AgentBrowserPanel, { threadId: 'one' })))
    await act(async () => { await vi.advanceTimersByTimeAsync(150) })
    // An action refresh can overlap the older polling request.
    await h.click('browserReload')
    expect(views).toBeGreaterThan(1)
    await act(async () => first!({ ok: true, status: 200, body: JSON.stringify({ ...state, view_sequence: 1, url: 'https://old.example' }) }))
    expect(h.container.querySelector<HTMLInputElement>('[aria-label="browserAddressPlaceholder"]')?.value).toBe('https://new.example')
  } finally { await h.close(); vi.useRealTimers() }
})

it('answers the exact native dialog and preserves the original dispatched receipt', async () => {
  const state = { active: true, owner: 'user', generation: 2, tabs: [], log: [], artifacts: [], image: 'data:image/jpeg;base64,AA==', dialog: { id: 'dialog-now', type: 'prompt', message: 'Confirm draft' } }
  const h = mount(state)
  try {
    await act(async () => h.root.render(createElement(AgentBrowserPanel, { threadId: 'one' })))
    await act(async () => h.container.querySelector<HTMLButtonElement>('.ds-browser-status-trigger')!.click())
    expect(h.container.querySelector('[role="dialog"]')?.textContent).toContain('Confirm draft')
    expect(h.container.querySelector('textarea')?.disabled).toBe(true)
    await h.click('browserDialogAccept')
    expect(h.request).toHaveBeenCalledWith('/v1/threads/one/browser/action', 'POST', JSON.stringify({ action: 'handle_dialog', dialog_id: 'dialog-now', accept: true, text: '', generation: 2 }))
  } finally { await h.close() }
})

it('requires an explicit human assessment to clear a persisted unknown operation', async () => {
  const h = mount({ active: true, owner: 'user', generation: 2, tabs: [], log: [], artifacts: [], image: 'data:image/jpeg;base64,AA==', unresolved: [{ action_id: 'saved-unknown', execution: 'unknown' }] })
  try {
    await act(async () => h.root.render(createElement(AgentBrowserPanel, { threadId: 'one' })))
    await act(async () => h.container.querySelector<HTMLButtonElement>('.ds-browser-status-trigger')!.click())
    expect(h.container.textContent).toContain('browserOutcomeUnknown')
    expect(h.container.querySelector('textarea')?.disabled).toBe(true)
    await h.click('browserReviewedDone')
    expect(h.request).toHaveBeenCalledWith('/v1/threads/one/browser/action', 'POST', JSON.stringify({ action: 'resolve_operation', operation_id: 'saved-unknown', outcome: 'executed', reason: 'browserReviewedDone', generation: 2 }))
  } finally { await h.close() }
})

it('uploads only the files explicitly returned by the native picker', async () => {
  const h = mount({ active: true, owner: 'user', generation: 2, tabs: [], log: [], artifacts: [], image: 'data:image/jpeg;base64,AA==', file_chooser: { id: 'chooser-now', mode: 'selectSingle' } })
  window.dsGui.pickWorkspaceFiles = vi.fn(async () => ({ ok: true as const, paths: ['/fixture/draft.txt'], files: [{ path: '/fixture/draft.txt', size: 12 }] }))
  try {
    await act(async () => h.root.render(createElement(AgentBrowserPanel, { threadId: 'one' })))
    await act(async () => h.container.querySelector<HTMLButtonElement>('.ds-browser-status-trigger')!.click())
    await h.click('browserChooseFiles')
    expect(h.request).toHaveBeenCalledWith('/v1/threads/one/browser/action', 'POST', JSON.stringify({ action: 'upload', chooser_id: 'chooser-now', files: ['/fixture/draft.txt'], generation: 2 }))
  } finally { await h.close() }
})

it('opens HTML in the lightweight browser without a Python runtime or conversation', async () => {
  const h = mount()
  h.request.mockRejectedValue(new Error('Browser requires Python 3.11+ and: uv sync --extra browser'))
  const consumed = vi.fn()
  const edit = vi.fn()
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, {
      threadId: null, preferredUrl: 'http://localhost:5173/design.html',
      preferredFilePath: '/project/design.html', onPreferredUrlConsumed: consumed, onOpenFileInEditor: edit
    })))
    expect(h.container.querySelector('webview')?.getAttribute('src')).toBe('http://localhost:5173/design.html')
    expect(consumed).toHaveBeenCalledTimes(1)
    await h.click('browserMore')
    await h.click('browserEditSource')
    expect(edit).toHaveBeenCalledExactlyOnceWith('/project/design.html')
    expect(h.request).not.toHaveBeenCalled()
    expect(h.container.textContent).not.toContain('browserNeedThread')
    expect(h.container.textContent).not.toContain('browserNormalPreview')
    expect(h.container.textContent).not.toContain('browserAgentWorkspace')
  } finally { await h.close() }
})

it('reveals the agent on a live request and returns to lightweight HTML while keeping its guest', async () => {
  const h = mount()
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'first', agentRequest: 1 })))
    expect(h.request).toHaveBeenCalledWith('/v1/threads/first/browser/view', 'GET', undefined)
    expect(h.container.querySelector('.ds-browser-status')?.closest('.hidden')).toBeNull()
    await act(async () => h.root.render(createElement(BrowserWorkspace, {
      threadId: 'first', agentRequest: 1, preferredUrl: 'http://localhost:5173/design.html'
    })))
    expect(h.container.querySelector('.ds-browser-status')?.closest('.hidden')).not.toBeNull()
    const guest = h.container.querySelector('webview')
    expect(guest?.getAttribute('src')).toBe('http://localhost:5173/design.html')
    await h.click('browserMore')
    expect(h.container.textContent).not.toContain('browserSettingsAndHistory')
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'first', agentRequest: 2 })))
    await h.click('browserMore')
    expect(h.container.textContent).not.toContain('browserReturnToPages')
    expect(h.container.querySelector('webview')).toBe(guest)
  } finally { await h.close() }
})

it('returns to the preserved page after ending automation', async () => {
  const h = mount()
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, {
      threadId: 'one', agentRequest: 1, preferredUrl: 'http://localhost:5173/design.html'
    })))
    const guest = h.container.querySelector('webview')
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one', agentRequest: 2 })))
    await h.click('browserMore')
    await h.click('browserEndSession')
    expect(h.container.querySelector('webview')).toBe(guest)
    expect(guest?.closest('.hidden')).toBeNull()
    expect(h.request).toHaveBeenCalledWith('/v1/threads/one/browser/control', 'POST', '{"owner":"stopped","generation":2}')
  } finally { await h.close() }
})

it('does not expose the removed settings and history panel', async () => {
  const h = mount()
  try {
    await act(async () => h.root.render(createElement(AgentBrowserPanel, { blocks: [], threadId: 'one' })))
    expect(h.container.querySelector('[aria-label="browserSettingsAndHistory"]')).toBeNull()
    await h.click('browserMore')
    expect(h.container.textContent).not.toContain('browserSettingsAndHistory')
    expect(h.container.querySelector('[aria-label="browserSettingsAndHistory"]')).toBeNull()
  } finally { await h.close() }
})

it('returns control through the runtime without sending another user query', async () => {
  const h = mount()
  try {
    await act(async () => h.root.render(createElement(AgentBrowserPanel, { threadId: 'one' })))
    await act(async () => h.container.querySelector<HTMLButtonElement>('.ds-browser-status-trigger')!.click())
    await h.click('browserReturnControl')
    expect(resume).not.toHaveBeenCalled()
    expect(h.request).toHaveBeenCalledWith('/v1/threads/one/browser/control', 'POST', '{"owner":"agent","generation":2}')
    expect(h.container.querySelector('textarea')?.disabled).toBe(true)
    await act(async () => h.container.querySelector<HTMLButtonElement>('.ds-browser-status-trigger')!.click())
    await h.click('browserTakeControl')
    expect(h.container.querySelector('textarea')?.disabled).toBe(false)
  } finally { await h.close() }
})

it('sends IME text once, pastes privately and fences input by generation', async () => {
  const h = mount()
  try {
    await act(async () => h.root.render(createElement(AgentBrowserPanel, { threadId: 'one' })))
    const field = h.container.querySelector('textarea')!
    await act(async () => {
      field.dispatchEvent(new CompositionEvent('compositionstart', { bubbles: true }))
      field.value = '中文'; field.dispatchEvent(new InputEvent('input', { bubbles: true, isComposing: true }))
      field.dispatchEvent(new CompositionEvent('compositionend', { bubbles: true, data: '中文' }))
      field.dispatchEvent(new InputEvent('input', { bubbles: true }))
    })
    const inputs = h.request.mock.calls.filter(([path]) => path.endsWith('/input'))
    expect(inputs).toHaveLength(1)
    expect(JSON.parse(inputs[0][2]!)).toEqual({ kind: 'text', text: '中文', generation: 2 })
    expect(field.value).toBe('')
    await h.click('browserNewTab')
    expect(h.request).toHaveBeenCalledWith('/v1/threads/one/browser/action', 'POST', '{"action":"new_tab","generation":2}')
  } finally { await h.close() }
})

it('uses a dismissible dock menu and pauses the hidden browser without losing the address draft', async () => {
  vi.useFakeTimers()
  const h = mount()
  try {
    await act(async () => h.root.render(createElement(AgentBrowserPanel, { threadId: 'one', visible: true })))
    const address = h.container.querySelector<HTMLInputElement>('[aria-label="browserAddressPlaceholder"]')!
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(address, 'https://draft.example')
      address.dispatchEvent(new Event('input', { bubbles: true }))
    })
    await h.click('browserMore')
    expect(h.container.querySelector('[role="menu"]')?.classList.contains('ds-dock-menu')).toBe(true)
    expect(document.activeElement?.getAttribute('role')).toBe('menuitem')
    await act(async () => document.activeElement?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })))
    expect(h.container.querySelector('[role="menu"]')).toBeNull()
    expect(document.activeElement).toBe(h.container.querySelector('[aria-label="browserMore"]'))
    await h.click('browserMore')
    await act(async () => h.root.render(createElement(AgentBrowserPanel, { threadId: 'one', visible: false })))
    h.request.mockClear()
    await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
    expect(h.request).not.toHaveBeenCalled()
    expect(h.container.querySelector('textarea')?.disabled).toBe(true)
    expect(h.container.querySelector('[role="menu"]')).toBeNull()
    await act(async () => h.root.render(createElement(AgentBrowserPanel, { threadId: 'one', visible: true })))
    expect(h.request).toHaveBeenCalledWith('/v1/threads/one/browser/view', 'GET', undefined)
    expect(address.value).toBe('https://draft.example')
  } finally { await h.close(); vi.useRealTimers() }
})

it('opens HTML in a shared tab and reuses the same URL without replacing another page', async () => {
  const h = mount()
  const consumed = vi.fn()
  try {
    await act(async () => h.root.render(createElement(AgentBrowserPanel, { threadId: 'one', agentRequest: 1, preferredUrl: 'http://localhost:5173/design.html', preferredFilePath: '/project/design.html', onPreferredUrlConsumed: consumed })))
    expect(h.request).toHaveBeenCalledWith('/v1/threads/one/browser/action', 'POST', JSON.stringify({ action: 'new_tab', url: 'http://localhost:5173/design.html', generation: 2 }))
    expect(consumed).toHaveBeenCalledTimes(1)
    expect(h.container.textContent).not.toContain('browserDocumentPreview')
    await act(async () => h.root.render(createElement(AgentBrowserPanel, { threadId: 'one', preferredUrl: null })))
    await act(async () => h.root.render(createElement(AgentBrowserPanel, { threadId: 'one', preferredUrl: 'https://example.test' })))
    expect(h.request).toHaveBeenCalledWith('/v1/threads/one/browser/action', 'POST', JSON.stringify({ action: 'switch_tab', tab_id: 'first', generation: 2 }))
  } finally { await h.close() }
})

it('defers previews while the agent is operating and opens them after explicit handoff', async () => {
  const h = mount({ active: true, owner: 'agent', generation: 1, tabs: [], log: [], artifacts: [] })
  try {
    await act(async () => h.root.render(createElement(AgentBrowserPanel, { threadId: 'one', preferredUrl: 'http://localhost:5173/' })))
    expect(h.container.textContent).toContain('browserNeedsAttention')
    expect(h.request.mock.calls.some(([path]) => path.endsWith('/action'))).toBe(false)
    await act(async () => h.container.querySelector<HTMLButtonElement>('.ds-browser-status-trigger')!.click())
    await h.click('browserTakeControl')
    await act(async () => h.container.querySelector<HTMLButtonElement>('.ds-browser-status-trigger')!.click())
    const open = [...h.container.querySelectorAll<HTMLButtonElement>('.ds-browser-notice button')][0]
    await act(async () => open.click())
    expect(h.request).toHaveBeenCalledWith('/v1/threads/one/browser/action', 'POST', JSON.stringify({ action: 'new_tab', url: 'http://localhost:5173/', generation: 2 }))
    expect(h.container.textContent).not.toContain('browserPreviewWaiting')
  } finally { await h.close() }
})

it('opens the current local HTML source from More without exposing an editor action on ordinary websites', async () => {
  const h = mount({ active: true, owner: 'user', generation: 2, url: 'http://localhost:5173/page.html', tabs: [{ tab_id: 'html', title: 'Page', url: 'http://localhost:5173/page.html', active: true }], log: [], artifacts: [] })
  const edit = vi.fn()
  try {
    await act(async () => h.root.render(createElement(AgentBrowserPanel, {
      threadId: 'one', preferredUrl: 'http://localhost:5173/page.html', preferredFilePath: '/project/page.html', onOpenFileInEditor: edit
    })))
    await h.click('browserMore')
    await h.click('browserEditSource')
    expect(edit).toHaveBeenCalledExactlyOnceWith('/project/page.html')
    expect(h.container.querySelector('[role="menu"]')).toBeNull()
    await act(async () => h.root.render(createElement(AgentBrowserPanel, { key: 'two', threadId: 'two', onOpenFileInEditor: edit })))
    await h.click('browserMore')
    expect(h.container.textContent).not.toContain('browserEditSource')
  } finally { await h.close() }
})

it('keeps manual control and shows a retryable error when resume observation fails', async () => {
  const h = mount({ active: true, owner: 'user', generation: 2, task_paused: true, url: 'https://example.test', image: 'data:image/jpeg;base64,AA==', log: [], artifacts: [] })
  try {
    await act(async () => h.root.render(createElement(AgentBrowserPanel, { threadId: 'one' })))
    expect(h.container.textContent).toContain('browserTaskPaused')
    h.request.mockImplementation(async (path: string) => path.endsWith('/control')
      ? { ok: false, status: 409, body: JSON.stringify({ detail: 'Page disconnected; retry' }) }
      : { ok: true, status: 200, body: '{}' })
    await act(async () => h.container.querySelector<HTMLButtonElement>('.ds-browser-status-trigger')!.click())
    await h.click('browserReturnControl')
    await act(async () => h.container.querySelector<HTMLButtonElement>('.ds-browser-status-trigger')!.click())
    expect(h.container.textContent).toContain('Page disconnected; retry')
    expect(h.container.textContent).toContain('browserConnectionProblem')
    await act(async () => h.container.querySelector<HTMLButtonElement>('.ds-browser-status-trigger')!.click())
    expect(h.container.querySelector('textarea')?.disabled).toBe(false)
    expect(resume).not.toHaveBeenCalled()
  } finally { await h.close() }
})

it('disables repeated handoff clicks and shows the page-read status during resume', async () => {
  const h = mount()
  try {
    await act(async () => h.root.render(createElement(AgentBrowserPanel, { threadId: 'one' })))
    let finish!: (value: { ok: boolean; status: number; body: string }) => void
    h.request.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    await act(async () => h.container.querySelector<HTMLButtonElement>('.ds-browser-status-trigger')!.click())
    await h.click('browserReturnControl')
    expect(h.container.textContent).toContain('browserResuming')
    expect(h.container.querySelector('.ds-browser-control-details')).toBeNull()
    await act(async () => h.container.querySelector<HTMLButtonElement>('.ds-browser-status-trigger')!.click())
    const button = h.container.querySelector<HTMLButtonElement>('.ds-browser-control')!
    expect(button.disabled).toBe(true)
    await act(async () => button.click())
    expect(h.request.mock.calls.filter(([path]) => path.endsWith('/control'))).toHaveLength(1)
    await act(async () => finish({ ok: true, status: 200, body: JSON.stringify({ active: true, owner: 'agent', generation: 3, log: [], artifacts: [] }) }))
    expect(h.container.textContent).not.toContain('browserResuming')
  } finally { await h.close() }
})


it.each([
  { owner: 'agent', task_running: true, title: 'browserAgentControl', tone: 'is-agent' },
  { owner: 'agent', task_running: false, title: 'browserAgentReady', tone: 'is-idle' },
  { owner: 'agent', task_running: true, assistance: { id: 'help', status: 'pending' }, title: 'browserWaitingForYou', tone: 'is-attention' },
])('floats the complete $title panel inside the page with the correct control state', async ({ title, tone, ...state }) => {
  const h = mount({ active: true, generation: 2, log: [], artifacts: [], ...state })
  try {
    await act(async () => h.root.render(createElement(AgentBrowserPanel, { threadId: 'one' })))
    const bar = h.container.querySelector('.ds-browser-status')!
    expect(bar.parentElement).toBe(h.container.querySelector('.ds-browser-content'))
    expect(h.container.querySelector('.ds-shared-browser')?.firstElementChild).not.toBe(bar)
    expect(bar.classList.contains(tone)).toBe(true)
    expect(bar.querySelector('[role="status"]')?.textContent).toContain(title)
    expect(bar.querySelector('.ds-browser-control')).toBeNull()
    await act(async () => bar.querySelector<HTMLButtonElement>('.ds-browser-status-trigger')!.click())
    expect(bar.querySelector('.ds-browser-control')?.textContent).toContain('browserTakeControl')
  } finally { await h.close() }
})

it('disables screenshot input while frames are missing or polling fails', async () => {
  vi.useFakeTimers()
  const h = mount()
  const snapshot = { active: true, owner: 'user', generation: 2, image: null, tabs: [], log: [], artifacts: [] }
  try {
    await act(async () => h.root.render(createElement(AgentBrowserPanel, { threadId: 'one' })))
    expect(h.container.querySelector('textarea')?.disabled).toBe(false)
    h.request.mockResolvedValue({ ok: true, status: 200, body: JSON.stringify(snapshot) })
    await act(async () => { await vi.advanceTimersByTimeAsync(150) })
    expect(h.container.querySelector('textarea')?.disabled).toBe(true)
    h.request.mockRejectedValue(new Error('disconnected'))
    await act(async () => { await vi.advanceTimersByTimeAsync(150) })
    expect(h.container.querySelector('textarea')?.disabled).toBe(true)
    h.request.mockResolvedValue({ ok: true, status: 200, body: JSON.stringify({ ...snapshot, image: 'data:image/jpeg;base64,AA==' }) })
    await act(async () => { await vi.advanceTimersByTimeAsync(600) })
    expect(h.container.querySelector('textarea')?.disabled).toBe(false)
  } finally { await h.close(); vi.useRealTimers() }
})

it('binds UI navigation to the current generation', async () => {
  const h = mount()
  try {
    await act(async () => h.root.render(createElement(AgentBrowserPanel, { threadId: 'one' })))
    await h.click('browserReload')
    expect(h.request).toHaveBeenCalledWith('/v1/threads/one/browser/action', 'POST', '{"action":"reload","generation":2}')
  } finally { await h.close() }
})

it('keeps typing enabled during a busy frame, but fences a changed scene or owner', async () => {
  vi.useFakeTimers()
  const h = mount()
  let state: Record<string, unknown> = { active: true, owner: 'user', generation: 2, scene: { scene_id: 'same' }, tabs: [], log: [], artifacts: [], image: 'data:image/jpeg;base64,AA==', frame_status: 'ready' }
  h.request.mockImplementation(async () => ({ ok: true, status: 200, body: JSON.stringify(state) }))
  try {
    await act(async () => h.root.render(createElement(AgentBrowserPanel, { threadId: 'one' })))
    const field = h.container.querySelector('textarea')!
    field.focus()
    state = { ...state, image: null, frame_status: 'busy' }
    await act(async () => vi.advanceTimersByTimeAsync(60))
    expect(field.disabled).toBe(false)
    expect(document.activeElement).toBe(field)
    state = { ...state, scene: { scene_id: 'changed' } }
    await act(async () => vi.advanceTimersByTimeAsync(60))
    expect(field.disabled).toBe(true)
    state = { ...state, image: 'data:image/jpeg;base64,AA==', frame_status: 'ready' }
    await act(async () => vi.advanceTimersByTimeAsync(60))
    expect(field.disabled).toBe(false)
    state = { ...state, generation: 3, image: null, frame_status: 'busy' }
    await act(async () => vi.advanceTimersByTimeAsync(60))
    expect(field.disabled).toBe(true)
  } finally { await h.close(); vi.useRealTimers() }
})

it('opens compact login settings without disabling page input', async () => {
  const h = mount()
  try {
    await act(async () => h.root.render(createElement(AgentBrowserPanel, { threadId: 'one' })))
    await h.click('browserMore')
    await h.click('browserCookieManage')
    expect(document.querySelector('.ds-browser-cookie-settings')).not.toBeNull()
    expect(h.container.querySelector('textarea')?.disabled).toBe(false)
    await h.click('browserCookieDismiss')
    expect(document.querySelector('.ds-browser-cookie-settings')).toBeNull()
    expect(document.activeElement?.getAttribute('aria-label')).toBe('browserMore')
  } finally { await h.close() }
})

it('dismisses the control dropdown on Escape and outside pointer input', async () => {
  const h = mount()
  try {
    await act(async () => h.root.render(createElement(AgentBrowserPanel, { threadId: 'one' })))
    const trigger = h.container.querySelector<HTMLButtonElement>('.ds-browser-status-trigger')!
    await act(async () => { trigger.focus(); trigger.click() })
    expect(trigger.getAttribute('aria-expanded')).toBe('true')
    await act(async () => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })))
    expect(trigger.getAttribute('aria-expanded')).toBe('false')
    expect(document.activeElement).toBe(trigger)
    await act(async () => trigger.click())
    await act(async () => new Promise(resolve => setTimeout(resolve, 5)))
    await act(async () => document.body.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true })))
    expect(h.container.querySelector('.ds-browser-control-details')).toBeNull()
  } finally { await h.close() }
})

it('drags the compact control within the page without toggling it', async () => {
  const h = mount()
  try {
    await act(async () => h.root.render(createElement(AgentBrowserPanel, { threadId: 'one' })))
    const panel = h.container.querySelector<HTMLElement>('.ds-browser-status')!
    const trigger = panel.querySelector<HTMLButtonElement>('.ds-browser-status-trigger')!
    vi.spyOn(panel, 'getBoundingClientRect').mockReturnValue({ left: 208, top: 8, width: 184, height: 34 } as DOMRect)
    vi.spyOn(panel.parentElement!, 'getBoundingClientRect').mockReturnValue({ left: 0, top: 0, width: 600, height: 400 } as DOMRect)
    trigger.setPointerCapture = vi.fn()
    trigger.releasePointerCapture = vi.fn()
    const pointer = async (type: string, x: number, y: number) => {
      await act(async () => trigger.dispatchEvent(new PointerEvent(type, { bubbles: true, pointerId: 1, isPrimary: true, button: 0, clientX: x, clientY: y })))
    }
    await pointer('pointerdown', 230, 20)
    await pointer('pointermove', 2000, 2000)
    expect(panel.style.transform).toBe('translate(-100%, -100%)')
    await pointer('pointerup', 2000, 2000)
    await act(async () => trigger.dispatchEvent(new MouseEvent('click', { bubbles: true, detail: 1 })))
    expect(trigger.getAttribute('aria-expanded')).toBe('false')
    expect(trigger.releasePointerCapture).toHaveBeenCalledWith(1)
    await pointer('pointerdown', 230, 20)
    await pointer('pointermove', 232, 21)
    await pointer('pointerup', 232, 21)
    await act(async () => trigger.dispatchEvent(new MouseEvent('click', { bubbles: true, detail: 1 })))
    expect(trigger.getAttribute('aria-expanded')).toBe('true')
  } finally { await h.close() }
})

it('keeps unresolved work in the floating panel when review is postponed', async () => {
  const h = mount({ active: true, owner: 'user', generation: 2, tabs: [], log: [], artifacts: [], unresolved: [{ action_id: 'unknown', execution: 'unknown' }] })
  try {
    await act(async () => h.root.render(createElement(AgentBrowserPanel, { threadId: 'one' })))
    expect(h.container.textContent).toContain('browserWaitingForYou')
    expect(h.container.textContent).not.toContain('browserOutcomeUnknown')
    expect(h.container.querySelector('.ds-shared-browser > .ds-browser-notice')).toBeNull()
    await act(async () => h.container.querySelector<HTMLButtonElement>('.ds-browser-status-trigger')!.click())
    expect(h.container.querySelector('.ds-browser-control-details')?.textContent).toContain('browserOutcomeUnknown')
    await h.click('browserReviewLater')
    expect(h.container.textContent).toContain('browserWaitingForYou')
    expect(h.request.mock.calls.some(([, , body]) => body?.includes('resolve_operation'))).toBe(false)
  } finally { await h.close() }
})

it('refreshes an outdated input scene without replaying queued text or exposing a raw error', async () => {
  const h = mount()
  const original = h.request.getMockImplementation()!
  let inputs = 0
  h.request.mockImplementation(async (path, method, raw) => {
    if (path.endsWith('/input') && JSON.parse(raw!).kind === 'text') {
      inputs++
      return { ok: false, status: 409, body: JSON.stringify({ detail: 'Browser page changed; queued input was discarded' }) }
    }
    return original(path, method, raw)
  })
  try {
    await act(async () => h.root.render(createElement(AgentBrowserPanel, { threadId: 'one' })))
    await act(async () => {
      const field = h.container.querySelector('textarea')!
      for (const value of ['first', 'do not replay']) {
        field.value = value; field.dispatchEvent(new InputEvent('input', { bubbles: true }))
      }
    })
    expect(inputs).toBe(1)
    expect(h.container.textContent).toContain('browserInputDiscarded')
    expect(h.container.textContent).not.toContain('queued input was discarded')
    expect(h.container.querySelector('textarea')?.disabled).toBe(false)
    expect(h.request.mock.calls.filter(([path]) => path.endsWith('/view')).length).toBeGreaterThan(1)
  } finally { await h.close() }
})

it('prioritizes the review state and offers one next step before takeover', async () => {
  const h = mount({ active: true, owner: 'agent', task_running: true, generation: 2, tabs: [], log: [], artifacts: [],
    error: 'technical timeout', unresolved: [{ action_id: 'pending', action: 'open', target_url: 'https://example.test', execution: 'unknown' }] })
  try {
    await act(async () => h.root.render(createElement(AgentBrowserPanel, { threadId: 'one' })))
    expect(h.container.querySelector('[role=status]')?.textContent).toBe('browserWaitingForYou')
    await act(async () => h.container.querySelector<HTMLButtonElement>('.ds-browser-status-trigger')!.click())
    expect(h.container.querySelector('.ds-browser-control')?.textContent).toBe('browserInspectAndHandle')
    expect(h.container.textContent).not.toContain('browserReviewedDone')
    expect(h.container.textContent).not.toContain('technical timeout')
    await h.click('browserInspectAndHandle')
    expect(h.request).toHaveBeenCalledWith('/v1/threads/one/browser/action', 'POST', JSON.stringify({ action: 'observe', generation: 3 }))
    expect(h.container.textContent).toContain('https://example.test')
    expect(h.container.textContent).toContain('browserReviewedDone')
    expect(h.container.querySelector('.ds-browser-control')).toBeNull()
  } finally { await h.close() }
})

it('records a user demonstration and asks the agent to turn it into a skill', async () => {
  const h = mount()
  let demonstrating = false
  const base = { active: true, owner: 'user', generation: 2, url: 'https://example.test', image: 'data:image/jpeg;base64,AA==', tabs: [], log: [], artifacts: [] }
  h.request.mockImplementation(async (path: string, _method: string, raw?: string) => {
    if (path.endsWith('/workflows')) {
      const stop = JSON.parse(raw!).action === 'stop'
      demonstrating = !stop
      return { ok: true, status: 200, body: JSON.stringify(stop ? { recordingId: 'rec_demo', steps: 4 } : { ok: true }) }
    }
    return { ok: true, status: 200, body: JSON.stringify({ ...base, workflow_recording: demonstrating }) }
  })
  const saved = vi.fn()
  try {
    await act(async () => h.root.render(createElement(AgentBrowserPanel, { threadId: 'one', onDemonstrationSaved: saved })))
    await h.click('browserMore')
    await h.click('browserDemoStart')
    expect(h.request).toHaveBeenCalledWith('/v1/threads/one/browser/workflows', 'POST', '{"action":"start"}')
    expect(saved).not.toHaveBeenCalled()
    await h.click('browserMore')
    await h.click('browserDemoFinish')
    expect(h.request).toHaveBeenCalledWith('/v1/threads/one/browser/workflows', 'POST', '{"action":"stop"}')
    expect(saved).toHaveBeenCalledExactlyOnceWith('browserDemoMessage')
  } finally { await h.close() }
})

it('returning control ends a demonstration with a notice instead of another query', async () => {
  const h = mount({ active: true, owner: 'user', generation: 2, url: 'https://example.test', image: 'data:image/jpeg;base64,AA==', tabs: [], log: [], artifacts: [], workflow_recording: true })
  const saved = vi.fn()
  resume.mockClear()
  try {
    await act(async () => h.root.render(createElement(AgentBrowserPanel, { threadId: 'one', onDemonstrationSaved: saved })))
    await act(async () => h.container.querySelector<HTMLButtonElement>('.ds-browser-status-trigger')!.click())
    await h.click('browserReturnControl')
    expect(h.container.textContent).toContain('browserDemoSavedNotice')
    expect(saved).not.toHaveBeenCalled()
    expect(resume).not.toHaveBeenCalled()
  } finally { await h.close() }
})

it('offers a repeated workflow as a skill and remembers a dismissal', async () => {
  const suggestion = { id: 'sig', site: 'shop.example', count: 3, recording_id: 'rec_auto' }
  const state = { active: true, owner: 'agent', generation: 2, url: 'https://shop.example', image: 'data:image/jpeg;base64,AA==', tabs: [], log: [], artifacts: [], skill_suggestion: suggestion, skill_suggestions_enabled: true }
  const h = mount(state)
  const posted: string[] = []
  h.request.mockImplementation(async (path: string, _method: string, raw?: string) => {
    if (!path.endsWith('/skill-suggestions')) return { ok: true, status: 200, body: JSON.stringify(state) }
    posted.push(JSON.parse(raw!).action)
    return { ok: true, status: 200, body: JSON.stringify(suggestion) }
  })
  const saved = vi.fn()
  try {
    await act(async () => h.root.render(createElement(AgentBrowserPanel, { threadId: 'one', onDemonstrationSaved: saved })))
    expect(h.container.textContent).toContain('browserSuggestSkill')
    await h.click('browserSuggestDismiss')
    expect(saved).not.toHaveBeenCalled()
    await h.click('browserSuggestAccept')
    expect(saved).toHaveBeenCalledExactlyOnceWith('browserSuggestMessage')
    await h.click('browserMore')
    await h.click('browserSuggestOff')
    expect(posted).toEqual(['dismiss', 'accept', 'disable'])
  } finally { await h.close() }
})
