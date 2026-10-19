// @vitest-environment happy-dom
import { act, createElement, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { useThreadRightSidebar } from '../../hooks/use-thread-right-sidebar'
import { WorkbenchRightSidebar } from './WorkbenchRightSidebar'
import { addRightSidebarTab, removeRightSidebarTab, type RightSidebarPanels } from '../../lib/right-sidebar-state'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string, opts?: { name: string }) => opts ? `${key}:${opts.name}` : key }) }))
vi.mock('../../store/chat-store', () => ({ useChatStore: (select: (state: unknown) => unknown) => select({ activeThreadId: 'thread' }) }))
vi.mock('../../store/run-panel-store', () => ({ useRunPanelStore: (select: (state: unknown) => unknown) => select({ target: null }) }))
vi.mock('./RightSidebarCollapsedStrip', () => ({ RightSidebarCollapsedStrip: () => null }))
vi.mock('../AppTerminalPanel', () => ({ AppTerminalPanel: () => createElement('div', { 'data-terminal': '' }) }))
vi.mock('../workspace-editor/WorkspaceEditorPanel', () => ({ WorkspaceEditorPanel: () => createElement('div', null, 'file content') }))

globalThis.IS_REACT_ACT_ENVIRONMENT = true

it('opens from launcher, adds and reselects via menu, keeps terminal mounted, and closes back to launcher', async () => {
  function Harness() {
    const [state, setState] = useState<RightSidebarPanels>({ tabs: [], activeTab: null })
    return createElement(WorkbenchRightSidebar, {
      threadId: null,
      open: true, collapsed: false, tab: state.activeTab, tabs: state.tabs,
      onTabChange: (tab) => setState((s) => addRightSidebarTab(s, tab)),
      onCloseTab: (tab) => setState((s) => removeRightSidebarTab(s, tab)),
      width: 420, workspaceRoot: '', blocks: [], changesContext: 'branch',
      devPreviewBlocks: [], latestDevPreviewUrl: null,
      onChangesContextChange: vi.fn(), onToggleCollapsed: vi.fn(), onClose: vi.fn(),
      onToggleMaximize: vi.fn(), onBeginResize: vi.fn(), onOpenFileInEditor: vi.fn()
    })
  }
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  const click = async (selector: string) => {
    const button = host.querySelector<HTMLButtonElement>(selector)
    expect(button).toBeTruthy()
    await act(async () => button!.click())
  }
  try {
    await act(async () => root.render(createElement(Harness)))
    expect(host.querySelectorAll('nav button')).toHaveLength(4)
    expect(host.querySelectorAll('[aria-pressed]')).toHaveLength(1) // maximize only
    await click('nav button:nth-child(3)') // terminal in existing function order
    const terminal = host.querySelector('[data-terminal]')
    expect(host.querySelector('nav')).toBeNull()
    await click('[aria-haspopup="menu"]')
    expect(document.activeElement?.getAttribute('role')).toBe('menuitem')
    await click('[role="menuitem"]') // files
    expect(host.textContent).toContain('file content')
    expect(host.querySelector('[data-terminal]')).toBe(terminal)
    await click('[aria-haspopup="menu"]')
    await click('[role="menuitem"]') // files again
    expect(host.querySelectorAll('[aria-label^="rightSidebarCloseTab:"]')).toHaveLength(2)
    await click('[aria-haspopup="menu"]')
    await act(async () => document.activeElement?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })))
    expect(host.querySelector('[role="menu"]')).toBeNull()
    expect(document.activeElement).toBe(host.querySelector('[aria-haspopup="menu"]'))
    await click('[aria-label="rightSidebarCloseTab:rightSidebarTabEditor"]')
    expect(host.querySelector('[data-terminal]')).toBe(terminal)
    await click('[aria-label="rightSidebarCloseTab:rightSidebarTabTerminal"]')
    expect(host.querySelectorAll('nav button')).toHaveLength(4)
  } finally {
    await act(async () => root.unmount())
    host.remove()
  }
})

it('loads on first open and preserves the panel across closing and reopening', async () => {
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  const noop = vi.fn()
  const render = (open: boolean) => act(async () => root.render(createElement(WorkbenchRightSidebar, {
    threadId: null,
    open, collapsed: false, tab: 'terminal', tabs: ['terminal'], width: 420,
    workspaceRoot: '', blocks: [], changesContext: 'branch', devPreviewBlocks: [],
    latestDevPreviewUrl: null, onCloseTab: noop, onTabChange: noop,
    onChangesContextChange: noop, onToggleCollapsed: noop, onClose: noop,
    onToggleMaximize: noop, onBeginResize: noop, onOpenFileInEditor: noop
  })))
  try {
    await render(false)
    const frame = host.querySelector('aside')!
    expect(host.querySelector('[data-terminal]')).toBeNull()
    await render(true)
    const terminal = host.querySelector('[data-terminal]')
    expect(terminal).not.toBeNull()
    await render(false)
    expect(host.querySelector('aside')).toBe(frame)
    expect(frame.style.width).toBe('0px')
    expect(frame.getAttribute('aria-hidden')).toBe('true')
    expect(frame.hasAttribute('inert')).toBe(true)
    expect(host.querySelector('[data-terminal]')).toBe(terminal)
    await render(true)
    expect(frame.style.width).toBe('420px')
    expect(frame.hasAttribute('inert')).toBe(false)
    expect(host.querySelector('[data-terminal]')).toBe(terminal)
  } finally {
    await act(async () => root.unmount())
    host.remove()
  }
})

vi.mock('../BrowserWorkspace', () => ({ BrowserWorkspace: ({ visible, threadId }: { visible: boolean; threadId: string }) =>
  createElement('input', { 'data-browser': threadId, 'data-visible': visible, defaultValue: 'draft' }) }))

it('preserves browser and terminal across dock switching and collapse, and restores each browser on thread change', async () => {
  const host = document.createElement('div'); const root = createRoot(host)
  const noop = vi.fn()
  const render = (tab: 'preview' | 'terminal', open = true, collapsed = false, threadId = 'first') => act(async () => root.render(createElement(WorkbenchRightSidebar, {
    threadId, open, collapsed, tab, tabs: ['preview', 'terminal'], width: 420,
    workspaceRoot: '', blocks: [], changesContext: 'branch', devPreviewBlocks: [],
    latestDevPreviewUrl: null, onCloseTab: noop, onTabChange: noop,
    onChangesContextChange: noop, onToggleCollapsed: noop, onClose: noop,
    onToggleMaximize: noop, onBeginResize: noop, onOpenFileInEditor: noop
  })))
  try {
    await render('preview')
    const browser = host.querySelector<HTMLInputElement>('[data-browser]')!
    const terminal = host.querySelector('[data-terminal]')
    browser.value = 'unsaved address'
    // The panel lets the browser page beneath it take input only while it shows.
    expect(host.querySelector('aside')?.hasAttribute('data-browser-shown')).toBe(true)
    await render('terminal')
    expect(host.querySelector('aside')?.hasAttribute('data-browser-shown')).toBe(false)
    expect(host.querySelector('[data-browser]')).toBe(browser)
    expect(browser.dataset.visible).toBe('false')
    await render('preview', true, true)
    expect(host.querySelector('[data-browser]')).toBe(browser)
    expect(host.querySelector('[data-terminal]')).toBe(terminal)
    expect(host.querySelector('aside')?.style.width).toBe('52px')
    await render('preview', false)
    expect(host.querySelector('[data-browser]')).toBe(browser)
    await render('preview')
    expect(browser.value).toBe('unsaved address')
    expect(browser.dataset.visible).toBe('true')
    await render('preview', true, false, 'second')
    const second = host.querySelector<HTMLInputElement>('[data-browser="second"]')!
    expect(second).not.toBe(browser)
    expect(second.value).toBe('draft')
    expect(browser.dataset.visible).toBe('false')
    second.value = 'second address'
    await render('terminal', false, false, 'new-chat')
    expect(host.querySelector('[data-browser="first"]')).toBe(browser)
    await render('preview', true, false, 'first')
    expect(host.querySelector('[data-browser="first"]')).toBe(browser)
    expect(browser.value).toBe('unsaved address')
    expect(browser.dataset.visible).toBe('true')
    expect(second.dataset.visible).toBe('false')
    await render('preview', true, false, 'second')
    expect(second.value).toBe('second address')
    expect(second.dataset.visible).toBe('true')
  } finally { await act(async () => root.unmount()) }
})


it('keeps the original browser through a new conversation and disposes only explicitly closed panels', async () => {
  let dock!: ReturnType<typeof useThreadRightSidebar>
  function Harness({ threadId }: { threadId: string | null }) {
    dock = useThreadRightSidebar(threadId)
    return createElement(WorkbenchRightSidebar, {
      threadId, open: dock.open, collapsed: dock.collapsed,
      tab: dock.panels.activeTab, tabs: dock.panels.tabs, width: 420,
      workspaceRoot: '', blocks: [], changesContext: 'branch', devPreviewBlocks: [],
      latestDevPreviewUrl: null, onCloseTab: vi.fn(), onTabChange: vi.fn(),
      onChangesContextChange: vi.fn(), onToggleCollapsed: vi.fn(), onClose: vi.fn(),
      onToggleMaximize: vi.fn(), onBeginResize: vi.fn(), onOpenFileInEditor: vi.fn()
    })
  }
  const host = document.createElement('div'); const root = createRoot(host)
  const render = (threadId: string | null) => act(async () => root.render(createElement(Harness, { threadId })))
  const open = () => act(async () => {
    dock.setOpen(true)
    dock.setPanels({ tabs: ['preview'], activeTab: 'preview' })
  })
  try {
    await render('first')
    await open()
    const first = host.querySelector<HTMLInputElement>('[data-browser="first"]')!
    first.value = 'original page'
    await render(null)
    expect(host.querySelector('aside')?.getAttribute('aria-hidden')).toBe('true')
    expect(first.dataset.visible).toBe('false')
    await render('second')
    await open()
    const second = host.querySelector('[data-browser="second"]')
    await render('first')
    expect(host.querySelector('aside')?.getAttribute('aria-hidden')).toBe('false')
    expect(host.querySelector('[data-browser="first"]')).toBe(first)
    expect(first.value).toBe('original page')
    expect(first.dataset.visible).toBe('true')
    await act(async () => dock.setPanels({ tabs: [], activeTab: null }))
    expect(host.querySelector('[data-browser="first"]')).toBeNull()
    expect(host.querySelector('[data-browser="second"]')).toBe(second)
    await open()
    expect(host.querySelector('[data-browser="first"]')).not.toBe(first)
    await render('second')
    expect(host.querySelector('[data-browser="second"]')).toBe(second)
  } finally { await act(async () => root.unmount()) }
})
