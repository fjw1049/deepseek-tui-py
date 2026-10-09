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
  Object.defineProperty(window, 'dsGui', { configurable: true, value: { runtimeRequest: request } })
  const container = document.createElement('div'); document.body.append(container)
  const root = createRoot(container)
  const click = async (label: string): Promise<void> => { await act(async () => { const button = [...container.querySelectorAll('button')].find(b => b.textContent === label || b.getAttribute('aria-label') === label); expect(button).toBeTruthy(); button!.click() }) }
  return { root, container, request, click, close: async () => { await act(async () => root.unmount()); container.remove() } }
}

it('opens the shared browser by default and scopes it to the displayed conversation', async () => {
  const h = mount()
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { blocks: [], threadId: 'first' })))
    expect(h.request).toHaveBeenCalledWith('/v1/threads/first/browser/view', 'GET', undefined)
    expect(h.container.textContent).not.toContain('browserNormalPreview')
    await act(async () => h.root.render(createElement(BrowserWorkspace, { blocks: [], threadId: 'second' })))
    expect(h.request).toHaveBeenCalledWith('/v1/threads/second/browser/view', 'GET', undefined)
    await act(async () => h.root.render(createElement(BrowserWorkspace, { blocks: [], threadId: null })))
    expect(h.container.textContent).toContain('browserNeedThread')
  } finally { await h.close() }
})

it('keeps settings secondary without a separate development browser', async () => {
  const h = mount()
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { blocks: [], threadId: 'one' })))
    expect(h.container.querySelector('[aria-label="browserSettingsAndHistory"]')).toBeNull()
    await h.click('browserMore'); await h.click('browserSettingsAndHistory')
    expect(h.container.querySelector('[aria-label="browserSettingsAndHistory"]')).not.toBeNull()
    await h.click('browserCloseDetails')
    expect(h.container.querySelector('[aria-label="browserSettingsAndHistory"]')).toBeNull()
  } finally { await h.close() }
})

it('hands control back and explicitly resumes the correct chat', async () => {
  const h = mount()
  try {
    await act(async () => h.root.render(createElement(AgentBrowserPanel, { threadId: 'one' })))
    await h.click('browserReturnControl')
    expect(resume).toHaveBeenCalledWith('browserResumeMessage', undefined, { expectedThreadId: 'one' })
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
    expect(h.request).toHaveBeenCalledWith('/v1/threads/one/browser/action', 'POST', '{"action":"new_tab"}')
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
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one', preferredUrl: 'http://localhost:5173/design.html', preferredFilePath: '/project/design.html', onPreferredUrlConsumed: consumed })))
    expect(h.request).toHaveBeenCalledWith('/v1/threads/one/browser/action', 'POST', JSON.stringify({ action: 'new_tab', url: 'http://localhost:5173/design.html' }))
    expect(consumed).toHaveBeenCalledTimes(1)
    expect(h.container.textContent).not.toContain('browserDocumentPreview')
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one', preferredUrl: null })))
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one', preferredUrl: 'https://example.test' })))
    expect(h.request).toHaveBeenCalledWith('/v1/threads/one/browser/action', 'POST', JSON.stringify({ action: 'switch_tab', tab_id: 'first' }))
  } finally { await h.close() }
})

it('defers previews while the agent is operating and opens them after explicit handoff', async () => {
  const h = mount({ active: true, owner: 'agent', generation: 1, tabs: [], log: [], artifacts: [] })
  try {
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'one', preferredUrl: 'http://localhost:5173/' })))
    expect(h.container.textContent).toContain('browserPreviewWaiting')
    expect(h.request.mock.calls.some(([path]) => path.endsWith('/action'))).toBe(false)
    await h.click('browserTakeControl')
    const open = [...h.container.querySelectorAll<HTMLButtonElement>('.ds-browser-notice button')][0]
    await act(async () => open.click())
    expect(h.request).toHaveBeenCalledWith('/v1/threads/one/browser/action', 'POST', JSON.stringify({ action: 'new_tab', url: 'http://localhost:5173/' }))
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
    await act(async () => h.root.render(createElement(BrowserWorkspace, { threadId: 'two', onOpenFileInEditor: edit })))
    await h.click('browserMore')
    expect(h.container.textContent).not.toContain('browserEditSource')
  } finally { await h.close() }
})
