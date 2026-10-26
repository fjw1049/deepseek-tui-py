// @vitest-environment happy-dom
import { act, createElement, Profiler, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { Workbench } from './Workbench'
import { useChatStore } from '../store/chat-store'

const { t, sidebarControl } = vi.hoisted(() => ({ t: (key: string) => key, sidebarControl: { setOpen: (_open: boolean) => {} } }))
vi.mock('react-i18next', async (importOriginal) => ({ ...await importOriginal<typeof import('react-i18next')>(), useTranslation: () => ({ t }) }))
vi.mock('../hooks/use-workspace-fs-watch', () => ({ useWorkspaceFsWatch: () => {} }))
vi.mock('../hooks/use-thread-right-sidebar', () => ({ useThreadRightSidebar: () => {
  const [open, setOpen] = useState(true)
  sidebarControl.setOpen = setOpen
  const [collapsed, setCollapsed] = useState(false)
  const [panels, setPanels] = useState({ tabs: ['changes'], activeTab: 'changes' })
  return { open, setOpen, collapsed, setCollapsed, panels, setPanels }
} }))
vi.mock('./chat/Sidebar', () => ({ Sidebar: () => createElement('div', null, 'sidebar content') }))
vi.mock('./chat/MessageTimeline', () => ({ MessageTimeline: () => createElement('div', null, 'chat content') }))
vi.mock('./chat/ComposerStage', () => ({ ComposerStage: () => null }))
vi.mock('./chat/SimpleEmptyPrompt', () => ({ SimpleEmptyPrompt: () => null }))
vi.mock('./chat/OperationContextDock', () => ({ OperationContextDock: () => {
  const [compact, setCompact] = useState(false)
  return createElement('button', { 'data-testid': 'dock', onClick: () => setCompact(!compact) }, compact ? 'compact' : 'expanded')
} }))
vi.mock('./SessionHeader', () => ({ SessionHeader: () => null }))
vi.mock('./SessionSharing', () => ({ SessionSharing: () => null, SharedLinkReceiver: () => null }))
vi.mock('./BrowserAssistance', () => ({ BrowserAssistance: () => null }))
vi.mock('./RuntimeDiagnosticsDialog', () => ({ RuntimeDiagnosticsDialog: () => null }))
vi.mock('./right-sidebar/WorkbenchRightSidebar', () => ({
  RightSidebarToggleButton: () => null, TerminalToggleButton: () => null,
  WorkbenchRightSidebar: ({ width, fillWidth, onBeginResize }: { width: number; fillWidth: boolean; onBeginResize: () => void }) =>
    createElement('aside', { className: 'ds-workbench-right-panel', style: { width: fillWidth ? '100%' : width } },
      createElement('div', { className: 'ds-right-panel-surface', style: { width } }, 'diff content'),
      createElement('div', { 'aria-label': 'rightPanelResize', onPointerDown: onBeginResize }))
}))

it.each(['sidebarResize', 'rightPanelResize'].flatMap(label => ['pointerup', 'pointercancel', 'blur'].map(ending => ({ label, ending }))))('previews $label without Workbench renders or storage writes and commits on $ending', async ({ label, ending }) => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  const initial = useChatStore.getState()
  const storage = new Map<string, string>()
  const save = vi.fn((key: string, value: string) => { storage.set(key, value) })
  vi.stubGlobal('localStorage', { getItem: (key: string) => storage.get(key) ?? null, setItem: save })
  const observers = vi.fn()
  vi.stubGlobal('ResizeObserver', class { constructor() { observers() } observe() {} disconnect() {} })
  const width = vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockImplementation(function (this: HTMLElement) {
    return this.classList.contains('ds-workbench-shell') ? 1600 : 1320
  })
  useChatStore.setState({ route: 'chat', workspaceRoot: '/repo', activeThreadId: null, blocks: [], threads: [], runtimeConnection: 'ready' })
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  const render = vi.fn()
  try {
    await act(async () => root.render(createElement(Profiler, { id: 'workbench', onRender: render }, createElement(Workbench))))
    const handle = host.querySelector<HTMLElement>(`[aria-label="${label}"]`)!
    expect(handle).toBeTruthy()
    const panel = host.querySelector<HTMLElement>(label === 'sidebarResize' ? '.ds-workbench-sidebar-wrap' : '.ds-workbench-right-panel')!
    const diffSurface = host.querySelector<HTMLElement>('.ds-right-panel-surface')!
    const diff = document.createElement('div')
    diff.className = 'ds-diff-view'
    diff.setAttribute('data-wrap', '')
    diff.innerHTML = '<div><table class="ds-diff-table"><tbody><tr><td>code</td></tr></tbody></table></div>'
    diffSurface.append(diff)
    const table = diff.querySelector('table')!
    Object.defineProperty(table, 'offsetWidth', { value: 600 })
    Object.defineProperty(table.parentElement!, 'clientHeight', { value: 300 })
    const startWidth = parseFloat(panel.style.width)
    const pointer = async (type: string, delta: number) => {
      await act(async () => (type === 'pointerdown' ? handle : window).dispatchEvent(new PointerEvent(type, {
        bubbles: true, pointerId: 1, button: 0, clientX: 500 + (label === 'sidebarResize' ? delta : -delta)
      })))
    }
    await pointer('pointerdown', 0)
    expect(table.style.width).toBe('600px')
    expect(table.style.minWidth).toBe('600px')
    const frames = new Map<number, FrameRequestCallback>()
    let frameId = 0
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => { frames.set(++frameId, callback); return frameId })
    vi.stubGlobal('cancelAnimationFrame', (id: number) => frames.delete(id))
    render.mockClear()
    save.mockClear()
    observers.mockClear()
    width.mockClear()
    await pointer('pointermove', 10)
    await pointer('pointermove', 20)
    expect(frames.size).toBe(1)
    await act(async () => { for (const callback of [...frames.values()]) callback(0) })
    expect(parseFloat(panel.style.width)).toBe(startWidth + 20)
    const shell = host.querySelector<HTMLElement>('.ds-workbench-shell')!
    expect(shell.style.getPropertyValue('--ds-sidebar-width')).toBe('')
    if (label === 'sidebarResize') {
      expect(host.querySelector<HTMLElement>('.ds-workbench-chrome-fill')!.style.left).toBe(`${startWidth + 20}px`)
    }
    expect(render).not.toHaveBeenCalled()
    expect(save).not.toHaveBeenCalled()
    expect(observers).not.toHaveBeenCalled()
    expect(width).not.toHaveBeenCalled()
    if (label === 'rightPanelResize') {
      await pointer('pointermove', 1200)
      await act(async () => { for (const callback of [...frames.values()]) callback(0) })
      expect(panel.style.width).toBe('100%')
      expect(host.querySelector<HTMLElement>('.ds-chat-column')!.inert).toBe(true)
      await pointer('pointermove', 20)
      await act(async () => { for (const callback of [...frames.values()]) callback(0) })
      expect(parseFloat(panel.style.width)).toBe(startWidth + 20)
      expect(host.querySelector<HTMLElement>('.ds-chat-column')!.inert).toBe(false)
      expect(render).not.toHaveBeenCalled()
    }
    await pointer('pointermove', 30)
    if (ending === 'blur') await act(async () => window.dispatchEvent(new Event('blur')))
    else await pointer(ending, 30)
    expect(parseFloat(panel.style.width)).toBe(startWidth + 30)
    expect(storage.get(label === 'sidebarResize' ? 'deepseekgui.layout.leftSidebarWidth' : 'deepseekgui.layout.rightInspectorWidth')).toBe(String(startWidth + 30))
    expect(frames.size).toBe(0)
    expect(table.style.width).toBe('')
    expect(table.style.minWidth).toBe('')
    expect(table.style.maxWidth).toBe('')
    await pointer('pointermove', 100)
    expect(parseFloat(panel.style.width)).toBe(startWidth + 30)
  } finally {
    await act(async () => root.unmount())
    host.remove()
    useChatStore.setState(initial, true)
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  }
})

it('preserves dismissed cards across opening and closing the right sidebar', async () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  const initial = useChatStore.getState()
  useChatStore.setState({ route: 'chat', workspaceRoot: '/repo', activeThreadId: 'a', blocks: [], threads: [], busy: true, runtimeConnection: 'ready' })
  const host = document.createElement('div')
  const root = createRoot(host)
  try {
    await act(async () => root.render(createElement(Workbench)))
    await act(async () => sidebarControl.setOpen(false))
    const cards = [...host.querySelectorAll<HTMLButtonElement>('[data-testid="dock"]')]
    expect(cards).toHaveLength(2)
    await act(async () => cards.forEach(card => card.click()))
    expect(cards.map(card => card.textContent)).toEqual(['compact', 'compact'])
    // The rail stays beside an open right sidebar.
    await act(async () => sidebarControl.setOpen(true))
    expect(host.querySelector<HTMLElement>('.ds-operation-rail')!.style.display).toBe('')
    await act(async () => sidebarControl.setOpen(false))
    expect([...host.querySelectorAll('[data-testid="dock"]')]).toEqual(cards)
    expect(cards.map(card => card.textContent)).toEqual(['compact', 'compact'])
    expect(host.querySelector<HTMLElement>('.ds-operation-rail')!.style.display).toBe('')
  } finally {
    await act(async () => root.unmount())
    useChatStore.setState(initial, true)
  }
})

it('shares the scroll cooldown between Monaco and native scrolling without rerendering', async () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  const initial = useChatStore.getState()
  useChatStore.setState({ route: 'chat', workspaceRoot: '/repo', activeThreadId: null, blocks: [], threads: [], runtimeConnection: 'ready' })
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  const render = vi.fn()
  try {
    await act(async () => root.render(createElement(Profiler, { id: 'workbench', onRender: render }, createElement(Workbench))))
    vi.useFakeTimers()
    const shell = host.querySelector<HTMLElement>('.ds-workbench-shell')!
    const editor = document.createElement('div')
    shell.append(editor)
    render.mockClear()
    const add = vi.spyOn(shell.classList, 'add')
    editor.dispatchEvent(new Event('ds-editor-scroll', { bubbles: true }))
    expect(shell.classList.contains('is-scrolling')).toBe(true)
    vi.advanceTimersByTime(100)
    editor.dispatchEvent(new Event('scroll'))
    vi.advanceTimersByTime(100)
    expect(shell.classList.contains('is-scrolling')).toBe(true)
    expect(add).toHaveBeenCalledTimes(1)
    vi.advanceTimersByTime(60)
    expect(shell.classList.contains('is-scrolling')).toBe(false)
    expect(render).not.toHaveBeenCalled()
    editor.dispatchEvent(new Event('ds-editor-scroll', { bubbles: true }))
    await act(async () => root.unmount())
    expect(shell.classList.contains('is-scrolling')).toBe(false)
    editor.dispatchEvent(new Event('ds-editor-scroll', { bubbles: true }))
    expect(shell.classList.contains('is-scrolling')).toBe(false)
  } finally {
    await act(async () => root.unmount())
    host.remove()
    vi.useRealTimers()
    vi.restoreAllMocks()
    useChatStore.setState(initial, true)
  }
})
