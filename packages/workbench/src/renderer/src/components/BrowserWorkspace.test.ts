// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { beforeEach, expect, it, vi } from 'vitest'
import { BrowserWorkspace, searchUrl } from './BrowserWorkspace'
import { requestBrowserDemo, useBrowserDemoStore } from '../store/browser-demo-store'
import { markPageReady, registerPageWebview, updatePageTab, useBrowserPagesStore, type PageWebview } from '../store/browser-pages-store'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
beforeEach(() => { useBrowserPagesStore.setState({ sessions: {}, display: null }) })
const nativeTab = (browserId: string) => {
  const session = useBrowserPagesStore.getState().sessions[browserId]!
  return session.tabs.find(tab => tab.id === session.activeTabId)!
}
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
const resume = vi.hoisted(() => vi.fn(async () => true))
vi.mock('../store/chat-store', () => ({ useChatStore: { getState: () => ({ sendMessage: resume }) } }))

function mount(state = { active: true, owner: 'user', generation: 2, url: 'https://example.test', image: 'data:image/jpeg;base64,AA==', tabs: [{ tab_id: 'first', title: 'Example', url: 'https://example.test/', active: true }], log: [], artifacts: [] } as Record<string, unknown>) {
  const request = vi.fn(async (path: string, _method: string, raw?: string) => {
    if (path.endsWith('/control')) { const owner = JSON.parse(raw!).owner; state = { ...state, owner, active: owner !== 'stopped', generation: Number(state.generation) + 1 } }
    return { ok: true, status: 200, body: JSON.stringify(path.endsWith('/workflows') ? { items: [] } : path.endsWith('/input') ? { success: true } : state) }
  })
  Object.defineProperty(window, 'dsGui', { configurable: true, value: { openExternal: vi.fn(async () => {}), runtimeRequest: request } })
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
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one' })))
    vi.useFakeTimers()
    await h.click('browserReload')
    expect(executed).toBe(1)
    await act(async () => h.container.querySelector<HTMLButtonElement>('.ds-browser-status-trigger')!.click())
    expect(h.container.textContent).toContain('browserActionSentViewUnavailable')
    expect(h.container.querySelector('textarea')?.disabled).toBe(true)
    expect(h.container.querySelector('.ds-browser-feedback')?.parentElement?.classList.contains('ds-browser-content')).toBe(true)
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
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one' })))
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
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one' })))
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
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one' })))
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
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one' })))
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
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one' })))
    await act(async () => h.container.querySelector<HTMLButtonElement>('.ds-browser-status-trigger')!.click())
    await h.click('browserChooseFiles')
    expect(h.request).toHaveBeenCalledWith('/v1/threads/one/browser/action', 'POST', JSON.stringify({ action: 'upload', chooser_id: 'chooser-now', files: ['/fixture/draft.txt'], generation: 2 }))
  } finally { await h.close() }
})

it('browses before a conversation exists in a preview session agents never use', async () => {
  const h = mount({ active: true, owner: 'user', generation: 2, url: 'about:blank', tabs: [], log: [], artifacts: [] })
  const consumed = vi.fn()
  const edit = vi.fn()
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, {
      threadId: null, preferredUrl: 'http://localhost:5173/design.html',
      preferredFilePath: '/project/design.html', onPreferredUrlConsumed: consumed, onOpenFileInEditor: edit
    })))
    expect(h.request).toHaveBeenCalledWith('/v1/threads/workbench-preview/browser/view', 'GET', undefined)
    expect(h.request).toHaveBeenCalledWith('/v1/threads/workbench-preview/browser/action', 'POST', JSON.stringify({ action: 'new_tab', url: 'http://localhost:5173/design.html', generation: 2 }))
    expect(consumed).toHaveBeenCalledTimes(1)
    await h.click('browserMore')
    expect(h.container.textContent).not.toContain('browserDemoStart')
  } finally { await h.close() }
})

it('ends the shared session from More', async () => {
  const h = mount()
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one' })))
    await h.click('browserMore')
    await h.click('browserEndSession')
    expect(h.request).toHaveBeenCalledWith('/v1/threads/one/browser/control', 'POST', '{"owner":"stopped","generation":2}')
  } finally { await h.close() }
})

it('does not expose the removed settings and history panel', async () => {
  const h = mount()
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { blocks: [], threadId: 'one' })))
    expect(h.container.querySelector('[aria-label="browserSettingsAndHistory"]')).toBeNull()
    await h.click('browserMore')
    expect(h.container.textContent).not.toContain('browserSettingsAndHistory')
    expect(h.container.querySelector('[aria-label="browserSettingsAndHistory"]')).toBeNull()
  } finally { await h.close() }
})

it('returns control through the runtime without sending another user query', async () => {
  const h = mount()
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one' })))
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
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one' })))
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
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one', visible: true })))
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
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one', visible: false })))
    h.request.mockClear()
    await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
    expect(h.request).not.toHaveBeenCalled()
    expect(h.container.querySelector('textarea')?.disabled).toBe(true)
    expect(h.container.querySelector('[role="menu"]')).toBeNull()
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one', visible: true })))
    expect(h.request).toHaveBeenCalledWith('/v1/threads/one/browser/view', 'GET', undefined)
    expect(address.value).toBe('https://draft.example')
  } finally { await h.close(); vi.useRealTimers() }
})

it('opens HTML in a shared tab and reuses the same URL without replacing another page', async () => {
  const h = mount()
  const consumed = vi.fn()
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one', preferredUrl: 'http://localhost:5173/design.html', preferredFilePath: '/project/design.html', onPreferredUrlConsumed: consumed })))
    expect(h.request).toHaveBeenCalledWith('/v1/threads/one/browser/action', 'POST', JSON.stringify({ action: 'new_tab', url: 'http://localhost:5173/design.html', generation: 2 }))
    expect(consumed).toHaveBeenCalledTimes(1)
    expect(h.container.textContent).not.toContain('browserDocumentPreview')
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one', preferredUrl: null })))
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one', preferredUrl: 'https://example.test' })))
    expect(h.request).toHaveBeenCalledWith('/v1/threads/one/browser/action', 'POST', JSON.stringify({ action: 'switch_tab', tab_id: 'first', generation: 2 }))
  } finally { await h.close() }
})

it('defers previews while the agent is operating and opens them after explicit handoff', async () => {
  const h = mount({ active: true, owner: 'agent', generation: 1, tabs: [], log: [], artifacts: [] })
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one', preferredUrl: 'http://localhost:5173/' })))
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
    await act(async () => h.root.render(createElement(BrowserWorkspace, {
      threadId: 'one', preferredUrl: 'http://localhost:5173/page.html', preferredFilePath: '/project/page.html', onOpenFileInEditor: edit
    })))
    await h.click('browserMore')
    await h.click('browserEditSource')
    expect(edit).toHaveBeenCalledExactlyOnceWith('/project/page.html')
    expect(h.container.querySelector('[role="menu"]')).toBeNull()
    await act(async () => h.root.render(createElement(BrowserWorkspace, { key: 'two', threadId: 'two', onOpenFileInEditor: edit })))
    await h.click('browserMore')
    expect(h.container.textContent).not.toContain('browserEditSource')
  } finally { await h.close() }
})

it('keeps manual control and shows a retryable error when resume observation fails', async () => {
  const h = mount({ active: true, owner: 'user', generation: 2, task_paused: true, url: 'https://example.test', image: 'data:image/jpeg;base64,AA==', log: [], artifacts: [] })
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one' })))
    expect(h.container.textContent).toContain('browserTaskPaused')
    h.request.mockImplementation(async (path: string) => path.endsWith('/control')
      ? { ok: false, status: 409, body: JSON.stringify({ detail: 'Page disconnected; retry' }) }
      : { ok: true, status: 200, body: '{}' })
    await h.click('browserReturnControl')
    await act(async () => h.container.querySelector<HTMLButtonElement>('.ds-browser-status-trigger')!.click())
    expect(h.container.textContent).toContain('Page disconnected; retry')
    expect(h.container.textContent).toContain('browserTaskPaused')
    expect(h.container.textContent).toContain('browserReturnControl')
    await act(async () => h.container.querySelector<HTMLButtonElement>('.ds-browser-status-trigger')!.click())
    expect(h.container.querySelector('textarea')?.disabled).toBe(false)
    expect(resume).not.toHaveBeenCalled()
  } finally { await h.close() }
})

it('disables repeated handoff clicks and shows the page-read status during resume', async () => {
  const h = mount()
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one' })))
    let finish!: (value: { ok: boolean; status: number; body: string }) => void
    h.request.mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    await h.click('browserReturnControl')
    expect(h.container.textContent).toContain('browserResuming')
    expect(h.container.querySelector('.ds-browser-control-details')).toBeNull()
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
  { owner: 'agent', task_running: true, assistance: { id: 'help', status: 'pending' }, title: 'browserWaitingForYou', tone: 'is-attention' },
])('leads the bottom bar with the $title status and an inline hand-over', async ({ title, tone, ...state }) => {
  const h = mount({ active: true, generation: 2, log: [], artifacts: [], ...state })
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one' })))
    const bar = h.container.querySelector('.ds-browser-status')!
    expect(bar.closest('.ds-annotation-toolbar')?.closest('.ds-browser-content')).toBeTruthy()
    expect(bar.classList.contains(tone)).toBe(true)
    expect(bar.querySelector('[role="status"]')?.textContent).toContain(title)
    expect(bar.querySelector('.ds-browser-control')?.textContent).toContain('browserTakeControl')
    expect(h.container.querySelector('[aria-label="annotationHide"]')).toBeNull()
  } finally { await h.close() }
})

it('hides the resting bar between tasks and brings it back when the agent takes over', async () => {
  const h = mount({ active: true, owner: 'user', task_running: false, generation: 2, image: 'data:image/jpeg;base64,AA==', tabs: [], log: [], artifacts: [] })
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one', onAttachImage: vi.fn(async () => true) })))
    // With no agent involved, "you have the page" says nothing, so the bar carries only its tools.
    const toolbar = h.container.querySelector('.ds-annotation-toolbar')!
    expect(toolbar.querySelector('.ds-browser-status')).toBeNull()
    expect(toolbar.firstElementChild?.classList.contains('ds-annotation-toolbar__divider')).toBe(false)
    await h.click('annotationHide')
    expect(h.container.querySelector('.ds-annotation-toolbar')?.closest('[inert]')).toBeTruthy()
    await h.click('browserMore')
    await h.click('browserShowAnnotationTools')
    expect(h.container.querySelector('.ds-annotation-toolbar')?.closest('[inert]')).toBeNull()
    await h.click('annotationHide')
    h.request.mockImplementation(async () => ({ ok: true, status: 200, body: JSON.stringify({ active: true, owner: 'agent', task_running: true, generation: 3, image: 'data:image/jpeg;base64,AA==', log: [], artifacts: [] }) }))
    await act(async () => new Promise(resolve => setTimeout(resolve, 100)))
    // The agent's page cannot be annotated, so the bar shows only the status and the takeover.
    const bar = [...h.container.querySelectorAll('.ds-browser-status')].find(item => !item.closest('[inert]'))!
    expect(bar.classList.contains('is-agent')).toBe(true)
    const shown = bar.closest('.ds-annotation-toolbar')!
    expect(shown.querySelector('[aria-label="annotationPen"], [aria-label="browserDemoStart"], [aria-label="annotationHide"]')).toBeNull()
    expect(shown.textContent).toContain('browserTakeControl')
    expect(h.container.querySelector<HTMLButtonElement>('[aria-label="browserAnnotate"]')?.disabled).toBe(true)
  } finally { window.localStorage.removeItem('ds-browser-annotation-bar-shown'); await h.close() }
})

it('keeps recording in the more menu, off the annotation bar', async () => {
  const h = mount({ active: true, owner: 'user', task_running: false, generation: 2, image: 'data:image/jpeg;base64,AA==', tabs: [], log: [], artifacts: [], capabilities: { video: { ready: false } } })
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one', onAttachImage: vi.fn(async () => true) })))
    const toolbar = h.container.querySelector('.ds-annotation-toolbar')!
    const order = [...toolbar.querySelectorAll('button')].map(b => b.getAttribute('aria-label'))
    expect(order.slice(order.indexOf('annotationText'))).toEqual(['annotationText', 'browserDemoStart', 'annotationHide'])
    await h.click('browserMore')
    await h.click('browserRecordScreen')
    expect(h.container.querySelector('.ds-dock-menu')).not.toBeNull()
    const video = h.container.querySelector<HTMLButtonElement>('[aria-label="browserRecordVideo"]')!
    expect(video.disabled).toBe(true)
    expect(document.getElementById(video.getAttribute('aria-describedby')!)?.textContent).toBe('browserVideoUnavailable')
    await h.click('browserRecordGif')
    expect(h.request).toHaveBeenCalledWith('/v1/threads/one/browser/action', 'POST', JSON.stringify({ action: 'record_start', generation: 2 }))
  } finally { await h.close() }
})

it('copies the FFmpeg install command when video is unavailable', async () => {
  const h = mount({ active: true, owner: 'user', generation: 2, log: [], artifacts: [], capabilities: { video: { ready: false } } })
  const writeText = vi.fn(async () => {})
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one' })))
    await h.click('browserMore'); await h.click('browserRecordScreen'); await h.click('browserCopyFfmpegCommand')
    expect(writeText).toHaveBeenCalledWith('brew install ffmpeg')
    expect(h.container.querySelector('.ds-browser-feedback')?.textContent).toContain('browserFfmpegCommandCopied')
  } finally { await h.close() }
})

it('keeps recording controls visible even when annotation tools were hidden', async () => {
  window.localStorage.setItem('ds-browser-annotation-bar-shown', '0')
  const h = mount({ active: true, owner: 'user', task_running: false, generation: 2, image: 'data:image/jpeg;base64,AA==', tabs: [], log: [], artifacts: [], recording: true, video_recording: true })
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one', onAttachImage: vi.fn(async () => true) })))
    const toolbar = h.container.querySelector('.ds-annotation-toolbar')!
    expect(toolbar.closest('.is-collapsed')).toBeNull()
    expect(toolbar.textContent).toContain('browserRecordingStop')
    expect(toolbar.textContent).toContain('00:00')
    expect(h.container.querySelector('[aria-label="annotationHide"]')).toBeNull()
    await h.click('browserRecordingStop')
    const actions = h.request.mock.calls.filter(([path]) => path.endsWith('/action')).map(([, , raw]) => JSON.parse(raw!).action)
    expect(actions).toEqual(['video_stop', 'record_stop'])
  } finally { window.localStorage.removeItem('ds-browser-annotation-bar-shown'); await h.close() }
})

it('disables screenshot input while frames are missing or polling fails', async () => {
  vi.useFakeTimers()
  const h = mount()
  const snapshot = { active: true, owner: 'user', generation: 2, image: null, tabs: [], log: [], artifacts: [] }
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one' })))
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

it('keeps a resting annotation bar on the page that picks, freezes for drawing, and can be hidden', async () => {
  window.localStorage.removeItem('ds-browser-annotation-bar-shown')
  // Between tasks: nothing to hand over, so the bar may be hidden.
  const h = mount({ active: true, owner: 'user', task_running: false, generation: 2, url: 'https://example.test', image: 'data:image/jpeg;base64,AA==', tabs: [{ tab_id: 'first', title: 'Example', url: 'https://example.test/', active: true }], log: [], artifacts: [] })
  const viewport = () => h.container.querySelector<HTMLElement>('.ds-browser-viewport')
  const header = () => h.container.querySelector<HTMLButtonElement>('.ds-dev-browser__toolbar [aria-pressed]')
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one', onAttachImage: vi.fn(), onPreviewPick: vi.fn() })))
    expect(h.container.querySelector('[role="toolbar"]')?.getAttribute('data-state')).toBe('rest')
    await h.click('browserAnnotate')
    expect(h.container.querySelector('[role="toolbar"]')?.getAttribute('data-state')).toBe('pick')
    expect(header()?.getAttribute('aria-label')).toBe('browserExitSelection')
    expect(viewport()?.style.cursor).toBe('crosshair')
    expect(h.container.querySelector('.ds-browser-feedback')).toBeNull()
    await h.click('annotationPen')
    await act(async () => {})
    expect(h.request).toHaveBeenCalledWith('/v1/threads/one/browser/view', 'GET', undefined)
    expect(h.container.querySelector('.ds-annotation__backdrop')?.getAttribute('src')).toBe('data:image/jpeg;base64,AA==')
    expect(viewport()?.style.cursor).toBe('')
    expect(header()?.getAttribute('aria-pressed')).toBe('true')
    await h.click('annotationClose')
    expect(h.container.querySelector('.ds-annotation__stage')).toBeNull()
    expect(h.container.querySelector('[role="toolbar"]')?.getAttribute('data-state')).toBe('rest')
    const content = h.container.querySelector<HTMLElement>('.ds-browser-content')!
    vi.spyOn(content, 'getBoundingClientRect').mockReturnValue(new DOMRect(0, 80, 800, 600))
    vi.spyOn(header()!, 'getBoundingClientRect').mockReturnValue(new DOMRect(730, 40, 30, 30))
    await h.click('annotationHide')
    expect(content.style.getPropertyValue('--annotation-collapse-x')).toBe('745px')
    expect(content.style.getPropertyValue('--annotation-collapse-bottom')).toBe('625px')
    expect(h.container.querySelector('.ds-annotation')?.getAttribute('aria-hidden')).toBe('true')
    expect(h.container.querySelector('.ds-annotation')?.hasAttribute('inert')).toBe(true)
    expect(header()?.getAttribute('aria-pressed')).toBe('false')
    expect(h.container.querySelector('.ds-annotation-launcher')).toBeNull()
    expect(document.activeElement).toBe(header())
    expect(window.localStorage.getItem('ds-browser-annotation-bar-shown')).toBe('false')
    await h.click('browserAnnotate')
    expect(h.container.querySelector('.ds-annotation-launcher')).toBeNull()
    expect(h.container.querySelector('.ds-annotation')?.hasAttribute('inert')).toBe(false)
    expect(header()?.getAttribute('aria-pressed')).toBe('true')
    expect(h.container.querySelector('[role="toolbar"]')?.getAttribute('data-state')).toBe('rest')
    await h.click('annotationHide')
    await h.click('browserAnnotate')
    expect(header()?.getAttribute('aria-pressed')).toBe('true')
    expect(h.container.querySelector('[role="toolbar"]')?.getAttribute('data-state')).toBe('rest')
  } finally { window.localStorage.removeItem('ds-browser-annotation-bar-shown'); await h.close() }
})

it('binds UI navigation to the current generation', async () => {
  const h = mount()
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one' })))
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
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one' })))
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
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one' })))
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
  const h = mount({ active: true, owner: 'user', generation: 2, tabs: [], log: [], artifacts: [], image: 'data:image/jpeg;base64,AA==', file_chooser: { id: 'chooser-now', mode: 'selectSingle' } })
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one' })))
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

it('keeps unresolved work in the floating panel when review is postponed', async () => {
  const h = mount({ active: true, owner: 'user', generation: 2, tabs: [], log: [], artifacts: [], unresolved: [{ action_id: 'unknown', execution: 'unknown' }] })
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one' })))
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
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one' })))
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
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one' })))
    expect(h.container.querySelector('[role=status]')?.textContent).toBe('browserWaitingForYou')
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

it('demonstrates from the bar, then lets the user review the steps in the activity card before adding them to the chat', async () => {
  const h = mount()
  let demonstrating = false
  let finishStop: (() => void) | null = null
  const base = { active: true, owner: 'user', generation: 2, url: 'https://example.test', image: 'data:image/jpeg;base64,AA==', tabs: [], log: [], artifacts: [] }
  const steps = [
    { id: '1', kind: 'open', url: 'https://example.test/shop' },
    { id: '2', kind: 'click', target: { name: '\nBuy\nnow' } },
    { id: '3', kind: 'fill', target: { name: 'Email' }, value: '{{email}}' },
    { id: '4', kind: 'click', target: { role: 'link' } }
  ]
  h.request.mockImplementation(async (path: string, _method: string, raw?: string) => {
    if (path.endsWith('/workflows')) {
      const body = JSON.parse(raw!)
      if (body.action === 'preview') return { ok: true, status: 200, body: JSON.stringify({ recordingId: 'rec_demo', steps }) }
      if (body.action === 'stop') await new Promise<void>(resolve => { finishStop = resolve })
      demonstrating = body.action === 'start'
      return { ok: true, status: 200, body: JSON.stringify(body.action === 'stop' ? { recordingId: 'rec_demo', steps: 4 } : { ok: true }) }
    }
    return { ok: true, status: 200, body: JSON.stringify({ ...base, workflow_recording: demonstrating }) }
  })
  const saved = vi.fn()
  const card = () => h.container.querySelector('.ds-annotation-toolbar .ds-browser-recording-activity.is-demo')
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one', onDemonstrationSaved: saved, onAttachImage: vi.fn(async () => true) })))
    await h.click('browserMore')
    expect(h.container.querySelector('[aria-label="browserDemoStart"][role="menuitem"]')).toBeNull()
    await h.click('browserDemoStart')
    expect(h.request).toHaveBeenCalledWith('/v1/threads/one/browser/workflows', 'POST', '{"action":"start","generation":2}')
    expect(useBrowserDemoStore.getState().active.one).toBe(true)
    const tool = h.container.querySelector<HTMLButtonElement>('.ds-annotation-toolbar [aria-label="browserDemoFinish"]')!
    expect(tool.getAttribute('aria-pressed')).toBe('true')
    // The demonstration lives in the card above the bar, the same place as screen recording.
    expect(h.container.querySelector('.ds-browser-recording-badge')).toBeNull()
    expect(card()?.textContent).toContain('browserDemoRecording00:00')
    expect(card()?.textContent).toContain('browserDemoRecordingHint')
    await act(async () => card()!.querySelector<HTMLButtonElement>('.ds-annotation-toolbar__primary')!.click())
    expect(h.request).toHaveBeenCalledWith('/v1/threads/one/browser/workflows', 'POST', '{"action":"stop"}')
    expect(card()?.textContent).toContain('browserDemoFinishing')
    expect(card()!.querySelector<HTMLButtonElement>('[aria-busy="true"]')?.disabled).toBe(true)
    expect(tool.disabled).toBe(true)
    await act(async () => finishStop!())
    expect(useBrowserDemoStore.getState().active.one).toBe(false)
    // Nothing reaches the chat until the user adds it; the steps are there to check first.
    expect(saved).not.toHaveBeenCalled()
    expect(card()?.textContent).toContain('browserDemoReviewTitle')
    expect(card()?.querySelector('ol')).toBeNull()
    await h.click('browserDemoReviewShow')
    expect(h.request).toHaveBeenCalledWith('/v1/threads/one/browser/workflows', 'POST', '{"action":"preview","recording_id":"rec_demo"}')
    expect([...card()!.querySelectorAll('li')].map(item => item.textContent))
      .toEqual(['browserDemoStepOpen', 'browserDemoStepClick', 'browserDemoStepFill', 'browserDemoStepUnnamed'])
    // Hiding and showing again reuses the steps already read.
    await h.click('browserDemoReviewHide')
    expect(card()?.querySelector('ol')).toBeNull()
    await h.click('browserDemoReviewShow')
    expect(h.request.mock.calls.filter(([, , raw]) => raw?.includes('"preview"'))).toHaveLength(1)
    await h.click('browserDemoReviewAdd')
    expect(saved).toHaveBeenCalledExactlyOnceWith('browserDemoMessage')
    expect(card()).toBeNull()
    expect(h.container.querySelector('.ds-browser-feedback')?.textContent).toContain('browserDemoDrafted')
  } finally { await h.close() }
})

it('closing a demonstration review adds nothing to the chat', async () => {
  const h = mount({ active: true, owner: 'user', generation: 2, url: 'https://example.test', image: 'data:image/jpeg;base64,AA==', tabs: [], log: [], artifacts: [], workflow_recording: true })
  const original = h.request.getMockImplementation()!
  let recording = true
  h.request.mockImplementation(async (path: string, method: string, raw?: string) => {
    if (path.endsWith('/workflows')) { recording = false; return { ok: true, status: 200, body: JSON.stringify({ recordingId: 'rec_demo', steps: 2 }) } }
    const response = await original(path, method, raw)
    return { ...response, body: JSON.stringify({ ...JSON.parse(response.body), workflow_recording: recording }) }
  })
  const saved = vi.fn()
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one', onDemonstrationSaved: saved, onAttachImage: vi.fn(async () => true) })))
    await h.click('browserDemoFinish')
    expect(h.container.querySelector('.ds-browser-recording-activity')?.textContent).toContain('browserDemoReviewTitle')
    await h.click('browserDemoReviewDismiss')
    expect(h.container.querySelector('.ds-browser-recording-activity')).toBeNull()
    expect(saved).not.toHaveBeenCalled()
  } finally { await h.close() }
})

it('keeps the demonstration review when its steps cannot be read, and reads them again on request', async () => {
  const h = mount({ active: true, owner: 'user', generation: 2, url: 'https://example.test', image: 'data:image/jpeg;base64,AA==', tabs: [], log: [], artifacts: [], workflow_recording: true })
  const original = h.request.getMockImplementation()!
  let previews = 0
  let recording = true
  h.request.mockImplementation(async (path: string, method: string, raw?: string) => {
    if (!path.endsWith('/workflows')) {
      const response = await original(path, method, raw)
      return { ...response, body: JSON.stringify({ ...JSON.parse(response.body), workflow_recording: recording }) }
    }
    if (!raw?.includes('"preview"')) { recording = false; return { ok: true, status: 200, body: JSON.stringify({ recordingId: 'rec_demo', steps: 1 }) } }
    return ++previews === 1 ? { ok: false, status: 409, body: JSON.stringify({ detail: 'missing steps' }) }
      : { ok: true, status: 200, body: JSON.stringify({ steps: [{ kind: 'press', key: 'Enter' }] }) }
  })
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one', onDemonstrationSaved: vi.fn(), onAttachImage: vi.fn(async () => true) })))
    await h.click('browserDemoFinish')
    await h.click('browserDemoReviewShow')
    const card = h.container.querySelector('.ds-browser-recording-activity')!
    expect(card.querySelector('[role="alert"]')?.textContent).toBe('browserDemoStepsFailed')
    expect(card.textContent).toContain('browserDemoReviewTitle')
    await h.click('browserDemoReviewHide')
    await h.click('browserDemoReviewShow')
    expect([...card.querySelectorAll('li')].map(item => item.textContent)).toEqual(['browserDemoStepPress'])
  } finally { await h.close() }
})

it('returning control ends a demonstration in the activity card instead of another query', async () => {
  for (const demonstration of [{ recordingId: 'rec_demo', steps: 3 }, { error: 'Recording contains incomplete browser capture' }, undefined]) {
    const h = mount({ active: true, owner: 'user', generation: 2, url: 'https://example.test', image: 'data:image/jpeg;base64,AA==', tabs: [], log: [], artifacts: [], workflow_recording: true })
    const original = h.request.getMockImplementation()!
    let returned = false
    h.request.mockImplementation(async (path: string, method: string, raw?: string) => {
      const response = await original(path, method, raw)
      returned ||= path.endsWith('/control')
      const next = { ...JSON.parse(response.body), workflow_recording: !returned }
      return { ...response, body: JSON.stringify(path.endsWith('/control') ? { ...next, demonstration } : next) }
    })
    const saved = vi.fn()
    resume.mockClear()
    try {
      await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one', onDemonstrationSaved: saved })))
      await h.click('browserReturnControl')
      const card = h.container.querySelector('.ds-browser-recording-activity')
      if (!demonstration) expect(h.container.textContent).toContain('browserDemoSavedNotice')
      else if ('error' in demonstration) expect(card?.textContent).toContain('browserDemoIncomplete')
      else expect(card?.textContent).toContain('browserDemoReviewTitle')
      expect(saved).not.toHaveBeenCalled()
      expect(resume).not.toHaveBeenCalled()
      if (demonstration && !('error' in demonstration)) {
        await h.click('browserDemoReviewAdd')
        expect(saved).toHaveBeenCalledExactlyOnceWith('browserDemoMessage')
      }
    } finally { await h.close() }
  }
})

it('leaves the hand-back between tasks to the runtime, which knows when a new task starts', async () => {
  const h = mount({ active: true, surface: 'native', owner: 'agent', task_running: false, generation: 2, log: [], artifacts: [] })
  vi.useFakeTimers()
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one' })))
    await act(async () => { await vi.advanceTimersByTimeAsync(2000) })
    expect(h.request.mock.calls.some(([path]) => path.endsWith('/control'))).toBe(false)
  } finally { vi.useRealTimers(); await h.close() }
})

it('offers no hand-back button while the user browses between tasks', async () => {
  const h = mount({ active: true, surface: 'native', owner: 'user', task_running: false, generation: 2, log: [], artifacts: [] })
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one' })))
    // Nothing to hand over, so nothing pins the bar up.
    expect(h.container.querySelector('.ds-browser-status')).toBeNull()
    expect(h.container.querySelector('.ds-browser-control')).toBeNull()
  } finally { await h.close() }
})

it('stops a loading page even while its navigation is still pending', async () => {
  const h = mount({ active: true, owner: 'user', generation: 2, loading: true, url: 'https://example.test', image: 'data:image/jpeg;base64,AA==', tabs: [], log: [], artifacts: [] })
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one' })))
    expect(h.container.querySelector('[aria-label="browserReload"]')).toBeNull()
    await h.click('browserStop')
    expect(h.request).toHaveBeenCalledWith('/v1/threads/one/browser/input', 'POST', '{"kind":"stop","generation":2}')
  } finally { await h.close() }
})

it('opens the default local preview in the Workbench tab from the empty page', async () => {
  const h = mount({ active: false, owner: 'agent', log: [], artifacts: [] })
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one' })))
    await h.click('browserOpenDefault')
    expect(nativeTab('one').url).toBe('http://127.0.0.1:5173/')
    expect(h.request.mock.calls.some(([path]) => path.endsWith('/action'))).toBe(false)
  } finally { await h.close() }
})

it('binds the runtime to the visible Workbench tabs and polls only control state', async () => {
  const h = mount({ active: false, owner: 'agent', log: [], artifacts: [] })
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one' })))
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)) })
    expect(h.request).toHaveBeenCalledWith('/v1/threads/one/browser/attach', 'POST', '{}')
    expect(h.request).toHaveBeenCalledWith('/v1/threads/one/browser', 'GET', undefined)
    expect(h.request.mock.calls.some(([path]) => path.endsWith('/view'))).toBe(false)
  } finally { await h.close() }
})

it('shields Workbench tabs while the agent works and lets the user browse them otherwise', async () => {
  let state: Record<string, unknown> = { active: true, surface: 'native', owner: 'agent', task_running: true, generation: 2, log: [], artifacts: [] }
  const h = mount(state)
  h.request.mockImplementation(async () => ({ ok: true, status: 200, body: JSON.stringify(state) }))
  vi.useFakeTimers()
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one' })))
    expect(h.container.querySelector('.ds-browser-shield')).not.toBeNull()
    expect(h.container.querySelector<HTMLInputElement>('[aria-label="browserAddressPlaceholder"]')?.disabled).toBe(true)
    expect(h.container.querySelector('.ds-shared-browser')?.classList.contains('is-native')).toBe(true)
    state = { ...state, owner: 'user', task_running: false }
    await act(async () => { await vi.advanceTimersByTimeAsync(700) })
    expect(h.container.querySelector('.ds-browser-shield')).toBeNull()
    expect(h.container.querySelector<HTMLInputElement>('[aria-label="browserAddressPlaceholder"]')?.disabled).toBe(false)
  } finally { vi.useRealTimers(); await h.close() }
})

it('opens previews in the blank Workbench tab, then in new tabs, with their source files', async () => {
  const h = mount({ active: true, surface: 'native', owner: 'user', generation: 2, log: [], artifacts: [] })
  const edit = vi.fn()
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, {
      threadId: 'one', preferredUrl: 'http://localhost:5173/design.html', preferredFilePath: '/project/design.html', onOpenFileInEditor: edit
    })))
    expect(useBrowserPagesStore.getState().sessions.one!.tabs).toHaveLength(1)
    expect(nativeTab('one')).toMatchObject({ url: 'http://localhost:5173/design.html', filePath: '/project/design.html' })
    await h.click('browserMore')
    await h.click('browserEditSource')
    expect(edit).toHaveBeenCalledExactlyOnceWith('/project/design.html')
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one', preferredUrl: 'http://localhost:5173/other.html' })))
    expect(useBrowserPagesStore.getState().sessions.one!.tabs.map(tab => tab.url)).toEqual(['http://localhost:5173/design.html', 'http://localhost:5173/other.html'])
    expect(h.request.mock.calls.some(([path]) => path.endsWith('/action'))).toBe(false)
  } finally { await h.close() }
})

it('loads typed addresses in the active Workbench tab and offers ending only for a task', async () => {
  const h = mount({ active: true, surface: 'native', owner: 'user', task_running: false, generation: 2, log: [], artifacts: [] })
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one' })))
    const loadURL = vi.fn(async () => {})
    registerPageWebview(nativeTab('one').id, Object.assign(document.createElement('webview'), { loadURL }) as unknown as PageWebview)
    markPageReady(nativeTab('one').id, true)
    const address = h.container.querySelector<HTMLInputElement>('[aria-label="browserAddressPlaceholder"]')!
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(address, 'localhost:3000')
      address.dispatchEvent(new Event('input', { bubbles: true }))
    })
    await act(async () => address.form!.requestSubmit())
    expect(loadURL).toHaveBeenCalledWith('http://localhost:3000/')
    await h.click('browserNewTab')
    expect(useBrowserPagesStore.getState().sessions.one!.tabs).toHaveLength(2)
    await h.click('browserMore')
    expect(h.container.textContent).not.toContain('browserEndSession')
  } finally { await h.close() }
})

it('places the Workbench tab under the page area in layout pixels when the UI is scaled', async () => {
  const layer = document.createElement('div')
  layer.className = 'ds-browser-page-layer'
  document.body.append(layer)
  // Body zoom 0.88: client rects shrink, the layer's own pixels do not.
  Object.defineProperty(layer, 'offsetWidth', { configurable: true, value: 1800 })
  layer.getBoundingClientRect = () => ({ left: 278, top: 7, width: 1584, height: 992 }) as DOMRect
  const h = mount({ active: true, surface: 'native', owner: 'user', generation: 2, log: [], artifacts: [] })
  try {
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      return (this.classList.contains('ds-browser-content') ? { left: 1071, top: 95, width: 791, height: 904 } : { left: 0, top: 0, width: 0, height: 0 }) as DOMRect
    })
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one' })))
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 50)) })
    expect(useBrowserPagesStore.getState().display).toEqual({ browserId: 'one', rect: { top: 100, left: 901, width: 899, height: 1027 } })
  } finally { vi.restoreAllMocks(); await h.close(); layer.remove() }
})

it('explains a failed load in the user language when the page gives no reason', async () => {
  const h = mount({ active: true, surface: 'native', owner: 'user', generation: 2, log: [], artifacts: [] })
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one' })))
    await act(async () => updatePageTab('one', nativeTab('one').id, { url: 'https://down.example/', error: '' }))
    expect(h.container.querySelector('.ds-browser-feedback')?.textContent).toBe('browserLoadFailed')
  } finally { await h.close() }
})

it('returns the tab to a blank page when the address is cleared', async () => {
  const h = mount({ active: true, surface: 'native', owner: 'user', generation: 2, log: [], artifacts: [] })
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one' })))
    const loadURL = vi.fn(async () => {})
    await act(async () => updatePageTab('one', nativeTab('one').id, { url: 'https://example.test/' }))
    registerPageWebview(nativeTab('one').id, Object.assign(document.createElement('webview'), { loadURL }) as unknown as PageWebview)
    markPageReady(nativeTab('one').id, true)
    const address = h.container.querySelector<HTMLInputElement>('[aria-label="browserAddressPlaceholder"]')!
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(address, '')
      address.dispatchEvent(new Event('input', { bubbles: true }))
    })
    await act(async () => address.form!.requestSubmit())
    expect(loadURL).toHaveBeenCalledWith('about:blank')
  } finally { await h.close() }
})

it('keeps trying to bind the visible tabs until Workbench has announced its bridge', async () => {
  const h = mount({ active: false, owner: 'agent', log: [], artifacts: [] })
  const original = h.request.getMockImplementation()!
  let attempts = 0
  h.request.mockImplementation(async (path, method, raw) => path.endsWith('/attach') && ++attempts === 1
    ? { ok: false, status: 409, body: JSON.stringify({ detail: 'Workbench browser is unavailable' }) }
    : original(path, method, raw))
  vi.useFakeTimers()
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one' })))
    await act(async () => { await vi.advanceTimersByTimeAsync(100) })
    expect(attempts).toBe(1)
    await act(async () => { await vi.advanceTimersByTimeAsync(5200) })
    expect(attempts).toBe(2)
  } finally { vi.useRealTimers(); await h.close() }
})


it('binds native recordings and demonstrations to the tab selected when requested', async () => {
  const h = mount({ active: true, surface: 'native', owner: 'user', task_running: false,
    generation: 2, log: [], artifacts: [] })
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one' })))
    await act(async () => updatePageTab('one', nativeTab('one').id, { url: 'https://example.test/' }))
    const tab = nativeTab('one').id
    await h.click('browserMore'); await h.click('browserRecordScreen'); await h.click('browserRecordGif')
    expect(h.request).toHaveBeenCalledWith('/v1/threads/one/browser/action', 'POST',
      JSON.stringify({ tab_id: tab, action: 'record_start', generation: 2 }))
    await act(async () => requestBrowserDemo('one'))
    expect(h.request).toHaveBeenCalledWith('/v1/threads/one/browser/workflows', 'POST',
      JSON.stringify({ action: 'start', generation: 2, tab_id: tab }))
  } finally { await h.close() }
})

it('blocks input in a demonstration tab until the recorder has attached there', async () => {
  vi.useFakeTimers()
  const state = { active: true, surface: 'native', owner: 'user', task_running: false,
    workflow_recording: true, workflow_tabs: [] as string[], generation: 2, log: [], artifacts: [] }
  const h = mount(state)
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one' })))
    expect(h.container.querySelector('.ds-browser-shield')).toBeTruthy()
    expect(h.container.querySelector<HTMLInputElement>('.ds-dev-browser__omnibox')?.disabled).toBe(true)
    state.workflow_tabs = [nativeTab('one').id]
    await act(async () => vi.advanceTimersByTimeAsync(600))
    expect(h.container.querySelector('.ds-browser-shield')).toBeNull()
    expect(h.container.querySelector<HTMLInputElement>('.ds-dev-browser__omnibox')?.disabled).toBe(false)
  } finally { await h.close(); vi.useRealTimers() }
})

it('keeps the page usable while an ordinary action is in flight', async () => {
  const h = mount({ active: true, surface: 'native', owner: 'user', task_running: false,
    generation: 2, log: [], artifacts: [] })
  const original = h.request.getMockImplementation()!
  let finish!: (value: { ok: boolean; status: number; body: string }) => void
  h.request.mockImplementation((path: string, method: string, raw?: string) => path.endsWith('/action')
    ? new Promise(resolve => { finish = resolve }) : original(path, method, raw))
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one' })))
    await act(async () => updatePageTab('one', nativeTab('one').id, { url: 'https://example.test/' }))
    await h.click('browserMore'); await h.click('browserRecordScreen'); await h.click('browserRecordGif')
    // Starting a recording must not take focus or input away from the page.
    expect(h.container.querySelector('.ds-browser-shield')).toBeNull()
    await act(async () => finish({ ok: true, status: 200, body: JSON.stringify({ success: true, content: '' }) }))
  } finally { await h.close() }
})

it('explains in plain words when a demonstration ends before its last step was captured, and starts again on request', async () => {
  const h = mount({ active: true, owner: 'user', generation: 2, url: 'https://example.test', image: 'data:image/jpeg;base64,AA==', tabs: [], log: [], artifacts: [], workflow_recording: true })
  const original = h.request.getMockImplementation()!
  let recording = true
  h.request.mockImplementation(async (path: string, method: string, raw?: string) => {
    if (path.endsWith('/workflows')) {
      recording = JSON.parse(raw!).action === 'start'
      return recording ? { ok: true, status: 200, body: '{}' }
        : { ok: false, status: 409, body: JSON.stringify({ detail: 'Recording contains incomplete browser capture; saved evidence requires review' }) }
    }
    const response = await original(path, method, raw)
    return { ...response, body: JSON.stringify({ ...JSON.parse(response.body), workflow_recording: recording }) }
  })
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one', onDemonstrationSaved: vi.fn(), onAttachImage: vi.fn(async () => true) })))
    await h.click('browserDemoFinish')
    const card = h.container.querySelector('.ds-annotation-toolbar .ds-browser-recording-activity.is-failed')!
    expect(card.querySelector('[role="alert"]')?.textContent).toBe('browserDemoSaveFailed')
    expect(card.textContent).toContain('browserDemoIncomplete')
    expect(h.container.querySelector('.ds-browser-feedback[role="alert"]')).toBeNull()
    // A demonstration that could not be saved is not a broken connection.
    expect(h.container.querySelector('.ds-browser-status')?.textContent).not.toContain('browserConnectionProblem')
    await h.click('browserDemoRetry')
    expect(h.request).toHaveBeenLastCalledWith('/v1/threads/one/browser/view', 'GET', undefined)
    expect(h.request).toHaveBeenCalledWith('/v1/threads/one/browser/workflows', 'POST', '{"action":"start","generation":2}')
    expect(h.container.querySelector('.ds-browser-recording-activity')?.textContent).toContain('browserDemoRecording')
  } finally { await h.close() }
})

it('runs screen recording and demonstration one at a time', async () => {
  useBrowserDemoStore.setState({ active: {}, request: null })
  const recording = mount({ active: true, owner: 'user', generation: 2, url: 'https://example.test', image: 'data:image/jpeg;base64,AA==', tabs: [], log: [], artifacts: [], video_recording: true })
  try {
    await act(async () => recording.root.render(createElement(BrowserWorkspace, { threadId: 'one', onAttachImage: vi.fn(async () => true) })))
    const tool = recording.container.querySelector<HTMLButtonElement>('.ds-annotation-toolbar [aria-label="browserDemoStart"]')!
    expect(tool.disabled).toBe(true)
    expect(tool.title).toBe('browserDemoBusyRecording')
    await act(async () => requestBrowserDemo('one'))
    expect(recording.request.mock.calls.some(([path]) => path.endsWith('/workflows'))).toBe(false)
    expect(recording.container.querySelector('.ds-browser-feedback')?.textContent).toContain('browserDemoBusyRecording')
  } finally { await recording.close() }
  const demo = mount({ active: true, owner: 'user', generation: 2, url: 'https://example.test', image: 'data:image/jpeg;base64,AA==', tabs: [], log: [], artifacts: [], workflow_recording: true })
  try {
    await act(async () => demo.root.render(createElement(BrowserWorkspace, { threadId: 'one', onAttachImage: vi.fn(async () => true) })))
    await demo.click('browserMore')
    const record = demo.container.querySelector<HTMLButtonElement>('[aria-label="browserRecordScreen"]')!
    expect(record.disabled).toBe(true)
    expect(document.getElementById(record.getAttribute('aria-describedby')!)?.textContent).toBe('browserRecordBusyDemo')
  } finally { await demo.close() }
})

it('brings hidden annotation tools back for a demonstration', async () => {
  window.localStorage.setItem('ds-browser-annotation-bar-shown', '0')
  const h = mount({ active: true, owner: 'user', task_running: false, generation: 2, url: 'https://example.test', image: 'data:image/jpeg;base64,AA==', tabs: [], log: [], artifacts: [], workflow_recording: true })
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one', onAttachImage: vi.fn(async () => true) })))
    const toolbar = h.container.querySelector('.ds-annotation-toolbar')!
    expect(toolbar.closest('.is-collapsed')).toBeNull()
    expect(toolbar.textContent).toContain('browserDemoRecording')
    expect(h.container.querySelector('[aria-label="annotationHide"]')).toBeNull()
  } finally { window.localStorage.removeItem('ds-browser-annotation-bar-shown'); await h.close() }
})

it('explains why a demonstration tab cannot be recorded', async () => {
  vi.useFakeTimers()
  const state = { active: true, surface: 'native', owner: 'user', task_running: false,
    workflow_recording: true, workflow_tabs: [] as string[], workflow_tab_errors: {} as Record<string, string>,
    generation: 2, log: [], artifacts: [] }
  const h = mount(state)
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one', onAttachImage: vi.fn(async () => true) })))
    await act(async () => updatePageTab('one', nativeTab('one').id, { url: 'https://example.test/' }))
    expect(h.container.querySelector('[role="alert"]')).toBeNull()
    expect(h.container.querySelector('.ds-browser-status')?.textContent).toContain('browserDemoAttaching')
    state.workflow_tab_errors = { [nativeTab('one').id]: 'page refused the recorder' }
    await act(async () => vi.advanceTimersByTimeAsync(600))
    expect(h.container.querySelector('[role="alert"]')?.textContent).toBe('browserDemoTabUnavailable')
    expect(h.container.querySelector('.ds-browser-shield')).toBeTruthy()
  } finally { await h.close(); vi.useRealTimers() }
})

it('never creates shared tabs or offers cookie import for a temporary session', async () => {
  const h = mount({ persistent: false, active: true, surface: 'headless', owner: 'user',
    generation: 2, tabs: [], log: [], artifacts: [], image: 'data:image/jpeg;base64,AA==' })
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'private' })))
    expect(useBrowserPagesStore.getState().sessions.private).toBeUndefined()
    expect(h.container.querySelector('.ds-shared-browser')?.classList.contains('is-native')).toBe(false)
    await act(async () => h.container.querySelector<HTMLButtonElement>('[aria-haspopup="menu"]')!.click())
    expect(h.container.textContent).not.toContain('browserCookieManage')
    expect(h.container.textContent).not.toContain('browserCookieUpdate')
  } finally { await h.close() }
})

it('waits for preferences before creating a shared browser', async () => {
  const h = mount()
  h.request.mockImplementation(() => new Promise(() => {}))
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'pending' })))
    expect(useBrowserPagesStore.getState().sessions.pending).toBeUndefined()
  } finally { await h.close() }
})

it('holds native input during standalone replay', async () => {
  const h = mount({ active: true, surface: 'native', owner: 'agent', task_running: false, demo_status: 'running', generation: 2, log: [], artifacts: [] })
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one' })))
    expect(h.container.querySelector('.ds-browser-shield')).not.toBeNull()
    expect(h.container.querySelector('.ds-browser-status')!.classList.contains('is-agent')).toBe(true)
    expect(h.container.querySelector('.ds-browser-status [role="status"]')!.textContent).toContain('browserAgentControl')
    expect(h.container.querySelector<HTMLInputElement>('[aria-label="browserAddressPlaceholder"]')!.disabled).toBe(true)
    expect(useBrowserPagesStore.getState().sessions.one!.inputBlocked).toBe(true)
  } finally { await h.close() }
})

it('keeps the live page usable while an unknown agent outcome waits for review', async () => {
  const h = mount({ active: true, surface: 'native', owner: 'user', generation: 2, image: 'data:image/jpeg;base64,AA==', log: [], artifacts: [],
    unresolved: [{ action_id: 'submit', action: 'click', execution: 'unknown', target_name: 'Place order' }] })
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one' })))
    expect(h.container.querySelector('.ds-shared-browser')!.classList.contains('is-native')).toBe(true)
    expect(h.container.querySelector<HTMLInputElement>('[aria-label="browserAddressPlaceholder"]')!.disabled).toBe(false)
    expect(useBrowserPagesStore.getState().sessions.one!.inputBlocked).toBe(false)
    // The review names what the agent acted on.
    await act(async () => h.container.querySelector<HTMLButtonElement>('.ds-browser-status-trigger')!.click())
    expect(h.container.textContent).toContain('browserReviewActionTarget')
  } finally { await h.close() }
})

it('holds only the tab the agent drives while it works', async () => {
  const h = mount({ active: true, surface: 'native', owner: 'agent', task_running: true, generation: 2, log: [], artifacts: [],
    tabs: [{ tab_id: 'agent-tab', title: 'Agent', url: 'https://example.test/', active: true }] })
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one' })))
    const session = useBrowserPagesStore.getState().sessions.one!
    expect(session.inputBlocked).toBe(true)
    expect(session.blockedTabId).toBe('agent-tab')
    // The user's own (active, different) tab stays usable.
    expect(h.container.querySelector('.ds-browser-shield')).toBeNull()
  } finally { await h.close() }
})

it('keeps a failed headless browser and offers explicit recovery', async () => {
  const h = mount({ active: false, surface: 'headless', healthy: false, owner: 'user', generation: 2, log: [], artifacts: [] })
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one' })))
    expect(h.container.querySelector('.ds-shared-browser')!.classList.contains('is-native')).toBe(false)
    expect(useBrowserPagesStore.getState().sessions.one).toBeUndefined()
    await act(async () => h.container.querySelector<HTMLButtonElement>('.ds-browser-status-trigger')!.click())
    await h.click('browserRecover')
    expect(h.request.mock.calls.some(([path]) => path.endsWith('/recover'))).toBe(true)
  } finally { await h.close() }
})

it('keeps a saved recording in the toolbar with a secondary file location action', async () => {
  const h = mount({ active: true, owner: 'user', generation: 2, log: [], artifacts: [] })
  const show = vi.fn(async () => {})
  window.dsGui.showItemInFolder = show
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one' })))
    h.request.mockImplementation(async (path: string) => path.endsWith('/action')
      ? { ok: true, status: 200, body: JSON.stringify({ success: true, artifact: { id: 'a.gif', label: 'GIF', path: '/tmp/a.gif' } }) }
      : { ok: true, status: 200, body: JSON.stringify({ active: true, owner: 'user', generation: 2, log: [], artifacts: [] }) })
    await h.click('browserMore'); await h.click('browserRecordScreen'); await h.click('browserRecordGif')
    expect(h.container.querySelector('.ds-browser-recording-activity')?.textContent).toContain('browserRecordingSaved')
    expect(h.container.textContent).toContain('browserViewGif')
    await h.click('browserRecordingFolder')
    expect(show).toHaveBeenCalledWith('/tmp/a.gif')
  } finally { await h.close() }
})

it('opens the most recent recording in an in-app preview from the menu', async () => {
  const h = mount({ active: true, owner: 'user', generation: 2, log: [], artifacts: [{ id: 'old.jpg', label: 'Old', path: '/tmp/old.jpg' }, { id: 'proof.gif', label: 'Proof', path: '/tmp/proof.gif' }] })
  const show = vi.fn(async () => {})
  window.dsGui.showItemInFolder = show
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one' })))
    expect(h.container.querySelector('details')).toBeNull()
    await h.click('browserMore'); await h.click('browserViewGif')
    expect(h.container.querySelector('dialog[open]')).not.toBeNull()
    expect(h.request).toHaveBeenCalledWith('/v1/threads/one/browser/artifacts/proof.gif', 'GET', undefined)
    expect(show).not.toHaveBeenCalled()
  } finally { await h.close() }
})

it('runs a demonstration requested from the chat composer, or explains why it cannot', async () => {
  useBrowserDemoStore.setState({ active: {}, request: null })
  const h = mount({ active: true, owner: 'user', generation: 2, url: 'https://example.test', image: 'data:image/jpeg;base64,AA==', tabs: [], log: [], artifacts: [] })
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one' })))
    await act(async () => requestBrowserDemo('two'))
    expect(h.request.mock.calls.some(([path]) => path.endsWith('/workflows'))).toBe(false)
    await act(async () => requestBrowserDemo('one'))
    expect(h.request).toHaveBeenCalledWith('/v1/threads/one/browser/workflows', 'POST', '{"action":"start","generation":2}')
    expect(useBrowserDemoStore.getState().request).toBeNull()
  } finally { await h.close() }
  const agent = mount({ active: true, owner: 'agent', task_running: true, generation: 2, url: 'https://example.test', image: 'data:image/jpeg;base64,AA==', tabs: [], log: [], artifacts: [] })
  try {
    await act(async () => agent.root.render(createElement(BrowserWorkspace, { threadId: 'one' })))
    await act(async () => requestBrowserDemo('one'))
    expect(agent.request.mock.calls.some(([path]) => path.endsWith('/workflows'))).toBe(false)
    expect(agent.container.querySelector('.ds-browser-feedback')?.textContent).toContain('browserDemoNeedsControl')
    expect(useBrowserDemoStore.getState().request).toBeNull()
  } finally { await agent.close() }
})

it('offers retry for a failed GIF save without starting another recording', async () => {
  const h = mount({ active: true, owner: 'user', generation: 2, image: 'data:image/jpeg;base64,AA==', tabs: [], log: [], artifacts: [], recording: false, recording_pending_save: true, recording_error: 'disk full' })
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one' })))
    expect(h.container.querySelector('[role="alert"]')?.textContent).toContain('browserRecordingFailed')
    await h.click('browserMore')
    expect(h.container.querySelector('[aria-label="browserRecordScreen"]')).toBeNull()
    await h.click('browserRecordingRetrySave')
    expect(h.request).toHaveBeenCalledWith('/v1/threads/one/browser/action', 'POST', JSON.stringify({ action: 'record_stop', generation: 2 }))
  } finally { await h.close() }
})

it('announces recordings saved by the runtime without a stop click', async () => {
  const state = { active: true, owner: 'user', generation: 2, image: 'data:image/jpeg;base64,AA==', tabs: [], log: [], artifacts: [] as { id: string; path: string; label: string }[], video_recording: true }
  const h = mount(state)
  vi.useFakeTimers()
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one' })))
    state.video_recording = false
    state.artifacts = [{ id: 'auto.webm', path: '/tmp/auto.webm', label: 'Video' }]
    await act(async () => { await vi.advanceTimersByTimeAsync(650) })
    expect(h.container.textContent).toContain('browserRecordingSaved')
    await act(async () => { await vi.advanceTimersByTimeAsync(6000) })
    expect(h.container.textContent).toContain('browserViewVideo')
    await h.click('browserRecordingDismiss')
    expect(h.container.querySelector('.ds-browser-recording-activity')).toBeNull()
    expect(h.request.mock.calls.some(([, , body]) => body?.includes('video_stop'))).toBe(false)
  } finally { await h.close(); vi.useRealTimers() }
})

it.each([['webm', 'video/webm', 'browserViewVideo'], ['gif', 'image/gif', 'browserViewGif']])('previews a saved %s inside the app', async (extension, mime, label) => {
  const artifact = { id: `saved.${extension}`, label: 'Recording', path: `/tmp/saved.${extension}` }
  const h = mount({ active: true, owner: 'user', generation: 2, tabs: [], log: [], artifacts: [artifact] })
  const original = h.request.getMockImplementation()!
  h.request.mockImplementation(async (path, method, raw) => path.includes('/artifacts/')
    ? { ok: true, status: 200, body: JSON.stringify({ image: `data:${mime};base64,AAAA` }) }
    : original(path, method, raw))
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one' })))
    await h.click('browserMore'); await h.click(label)
    const dialog = h.container.querySelector<HTMLDialogElement>('dialog')!
    expect(dialog.open).toBe(true)
    const media = dialog.querySelector(extension === 'webm' ? 'video' : 'img')!
    expect(media.getAttribute('src')).toBe(`data:${mime};base64,AAAA`)
    if (extension === 'webm') expect((media as HTMLVideoElement).controls).toBe(true)
    await h.click('browserRecordingPreviewClose')
    expect(h.container.querySelector('dialog')).toBeNull()
    expect(h.container.textContent).toContain(label)
  } finally { await h.close() }
})

it('keeps an explicit saving state until the stop request finishes', async () => {
  const state = { active: true, owner: 'user', generation: 2, tabs: [], log: [], artifacts: [], video_recording: true }
  const h = mount(state)
  const original = h.request.getMockImplementation()!
  let finish!: (result: { ok: boolean; status: number; body: string }) => void
  h.request.mockImplementation(async (path, method, raw) => path.endsWith('/action')
    ? new Promise(resolve => { finish = resolve }) : original(path, method, raw))
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one' })))
    await h.click('browserRecordingStop')
    const saving = h.container.querySelector<HTMLButtonElement>('.ds-browser-recording-activity button')!
    expect(saving.textContent).toBe('browserRecordingSaving')
    expect(saving.disabled).toBe(true)
    await act(async () => {
      state.video_recording = false
      finish({ ok: true, status: 200, body: JSON.stringify({ success: true, artifact: { id: 'a.webm', label: 'Video', path: '/tmp/a.webm' } }) })
    })
    expect(h.container.querySelector('.ds-browser-recording-activity')?.textContent).toContain('browserViewVideo')
    expect(h.container.textContent).not.toContain('browserRecordingSaving')
  } finally { await h.close() }
})

it('lets the user retry a recording preview without losing the saved result', async () => {
  const artifact = { id: 'saved.webm', label: 'Video', path: '/tmp/saved.webm' }
  const h = mount({ active: true, owner: 'user', generation: 2, tabs: [], log: [], artifacts: [artifact] })
  const original = h.request.getMockImplementation()!
  let attempts = 0
  h.request.mockImplementation(async (path, method, raw) => {
    if (!path.includes('/artifacts/')) return original(path, method, raw)
    if (++attempts === 1) throw new Error('Unavailable')
    return { ok: true, status: 200, body: JSON.stringify({ image: 'data:video/webm;base64,AAAA' }) }
  })
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one' })))
    await h.click('browserMore'); await h.click('browserViewVideo')
    expect(h.container.querySelector('dialog [role="alert"]')?.textContent).toContain('browserRecordingPreviewFailed')
    await h.click('browserRecordingPreviewRetry')
    expect(h.container.querySelector('dialog video')).not.toBeNull()
    expect(attempts).toBe(2)
  } finally { await h.close() }
})

it('searches with an engine reachable in the interface language', () => {
  expect(searchUrl('天气 北京', 'zh-CN')).toBe('https://www.baidu.com/s?wd=%E5%A4%A9%E6%B0%94%20%E5%8C%97%E4%BA%AC')
  expect(searchUrl('weather', 'en')).toBe('https://www.google.com/search?q=weather')
})

it('protects the agent-owned tab while another tab is shown', async () => {
  useBrowserPagesStore.setState({ sessions: { one: { activeTabId: 'human-tab', tabs: [
    { id: 'agent-tab', url: 'https://example.test/a', title: 'Agent page', filePath: null, loading: false, error: null },
    { id: 'human-tab', url: 'https://example.test/b', title: 'Human page', filePath: null, loading: false, error: null }
  ] } }, display: null })
  const h = mount({ active: true, surface: 'native', owner: 'agent', task_running: true, generation: 2, log: [], artifacts: [],
    tabs: [{ tab_id: 'agent-tab', title: 'Agent page', url: 'https://example.test/a', active: true },
      { tab_id: 'human-tab', title: 'Human page', url: 'https://example.test/b', active: false }] })
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one' })))
    const button = h.container.querySelector<HTMLButtonElement>('[aria-label="browserCloseTab Agent page"]')!
    expect(button.disabled).toBe(true)
    await act(async () => button.click())
    expect(useBrowserPagesStore.getState().sessions.one!.tabs.some(t => t.id === 'agent-tab')).toBe(true)
    const humanClose = h.container.querySelector<HTMLButtonElement>('[aria-label="browserCloseTab Human page"]')!
    expect(humanClose.disabled).toBe(false)
    await act(async () => humanClose.click())
    expect(useBrowserPagesStore.getState().sessions.one!.tabs.map(t => t.id)).toEqual(['agent-tab'])
    expect(h.request.mock.calls.some(([path]) => path.endsWith('/control'))).toBe(false)
  } finally { await h.close() }
})
