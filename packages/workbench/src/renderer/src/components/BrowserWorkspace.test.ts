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
  const click = async (label: string): Promise<void> => { await act(async () => { const button = [...container.querySelectorAll('button')].find(b => !b.closest('.hidden') && (b.textContent === label || b.getAttribute('aria-label') === label)); expect(button).toBeTruthy(); button!.click() }) }
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
    await h.click('browserReload')
    expect(executed).toBe(1)
    expect(h.container.textContent).toContain('browserActionSentViewUnavailable')
    expect(h.container.querySelector('textarea')?.disabled).toBe(true)
  } finally { await h.close() }
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
    await h.click('browserSettingsAndHistory')
    expect(h.container.querySelector('.ds-browser-details')).not.toBeNull()
    await h.click('browserMore')
    await h.click('browserReturnToPages')
    expect(h.container.querySelector('webview')).toBe(guest)
  } finally { await h.close() }
})

it('returns to the preserved page after ending automation', async () => {
  const h = mount()
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, {
      threadId: 'one', preferredUrl: 'http://localhost:5173/design.html'
    })))
    const guest = h.container.querySelector('webview')
    await h.click('browserMore')
    await h.click('browserSettingsAndHistory')
    await h.click('browserCloseDetails')
    await h.click('browserMore')
    await h.click('browserEndSession')
    expect(h.container.querySelector('webview')).toBe(guest)
    expect(guest?.closest('.hidden')).toBeNull()
    expect(h.request).toHaveBeenCalledWith('/v1/threads/one/browser/control', 'POST', '{"owner":"stopped","generation":2}')
  } finally { await h.close() }
})

it('keeps agent settings secondary', async () => {
  const h = mount()
  try {
    await act(async () => h.root.render(createElement(AgentBrowserPanel, { blocks: [], threadId: 'one' })))
    expect(h.container.querySelector('[aria-label="browserSettingsAndHistory"]')).toBeNull()
    await h.click('browserMore'); await h.click('browserSettingsAndHistory')
    expect(h.container.querySelector('[aria-label="browserSettingsAndHistory"]')).not.toBeNull()
    await h.click('browserCloseDetails')
    expect(h.container.querySelector('[aria-label="browserSettingsAndHistory"]')).toBeNull()
  } finally { await h.close() }
})

it('returns control through the runtime without sending another user query', async () => {
  const h = mount()
  try {
    await act(async () => h.root.render(createElement(AgentBrowserPanel, { threadId: 'one' })))
    await h.click('browserReturnControl')
    expect(resume).not.toHaveBeenCalled()
    expect(h.request).toHaveBeenCalledWith('/v1/threads/one/browser/control', 'POST', '{"owner":"agent","generation":2}')
    expect(h.container.querySelector('textarea')?.disabled).toBe(true)
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
    await act(async () => h.root.render(createElement(AgentBrowserPanel, { threadId: 'one', preferredUrl: 'http://localhost:5173/design.html', preferredFilePath: '/project/design.html', onPreferredUrlConsumed: consumed })))
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
    expect(h.container.textContent).toContain('browserPreviewWaiting')
    expect(h.request.mock.calls.some(([path]) => path.endsWith('/action'))).toBe(false)
    await h.click('browserTakeControl')
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
    await h.click('browserReturnControl')
    expect(h.container.textContent).toContain('Page disconnected; retry')
    expect(h.container.textContent).toContain('browserTaskPaused')
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
    await h.click('browserReturnControl')
    expect(h.container.textContent).toContain('browserResuming')
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
  { owner: 'agent', task_running: true, assistance: { id: 'help', status: 'pending' }, title: 'browserControlNeedsHelp', tone: 'is-attention' },
])('keeps $title above page navigation with the correct control state', async ({ title, tone, ...state }) => {
  const h = mount({ active: true, generation: 2, log: [], artifacts: [], ...state })
  try {
    await act(async () => h.root.render(createElement(AgentBrowserPanel, { threadId: 'one' })))
    const bar = h.container.querySelector('.ds-browser-status')!
    expect(h.container.querySelector('.ds-shared-browser')?.firstElementChild).toBe(bar)
    expect(bar.classList.contains(tone)).toBe(true)
    expect(bar.querySelector('[role="status"]')?.textContent).toContain(title)
    expect(bar.querySelector('button')?.textContent).toContain('browserTakeControl')
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
