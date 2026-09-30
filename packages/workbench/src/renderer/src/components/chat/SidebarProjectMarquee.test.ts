// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { useChatStore } from '../../store/chat-store'
import { SidebarProjectsColumn } from './SidebarProjectsSection'

vi.mock('../../store/chat-store', async () => {
  const { create } = await import('zustand')
  return { useChatStore: create((set) => ({
    threads: [], activeThreadId: null, pinnedThreadIds: [], blocks: [],
    hiddenWorkspacePaths: [], sidebarLabelColors: {}, watchTurnCompletion: {}, unreadThreadIds: {},
    projectsCollapsed: false, chatsCollapsed: false,
    setProjectsCollapsed: (projectsCollapsed: boolean) => set({ projectsCollapsed }),
    setChatsCollapsed: (chatsCollapsed: boolean) => set({ chatsCollapsed })
  })) }
})
vi.mock('../../hooks/use-thread-tasks', () => ({
  useThreadsWithActiveTasks: () => ({ threadIds: new Set(), taskIds: new Set() })
}))
globalThis.IS_REACT_ACT_ENVIRONMENT = true

it('scrolls a long project name when hovering the folder row and restores its fade on leave', async () => {
  vi.useFakeTimers()
  vi.stubGlobal('ResizeObserver', class {
    observe(): void {}
    disconnect(): void {}
  })
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(100)
  vi.spyOn(HTMLElement.prototype, 'scrollWidth', 'get').mockReturnValue(200)
  vi.spyOn(window, 'getComputedStyle').mockReturnValue({ transform: 'none' } as CSSStyleDeclaration)
  const animation = { cancel: vi.fn(), onfinish: null }
  const animate = vi.fn().mockReturnValue(animation)
  const originalAnimate = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'animate')
  Object.defineProperty(HTMLElement.prototype, 'animate', { configurable: true, value: animate })
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  const noop = vi.fn()
  try {
    await act(async () => useChatStore.getState().setProjectsCollapsed(false))
    await act(async () => root.render(createElement(SidebarProjectsColumn, {
      threads: [], activeThreadId: null, runtimeReady: true,
      workspaceRoot: '/test/grok-bot-0.18-reconstructed-main', busy: false,
      watchTurnCompletion: {}, unreadThreadIds: {}, pinnedThreadIds: [], locale: 'en',
      onSelectThread: noop, onOpenThreadTerminal: noop, onDeleteThread: noop,
      onArchiveThread: noop, onTogglePin: noop, onPickWorkspace: noop,
      onRemoveWorkspace: noop, onDeleteWorkspace: noop, onCreateThreadInWorkspace: noop,
      t: (key: string) => key
    })))
    const header = container.querySelector('.ds-sidebar-workspace')!
    const label = header.querySelector('.ds-sidebar-project-label')!
    await act(async () => header.querySelector('svg')!.dispatchEvent(new MouseEvent('mouseover', { bubbles: true })))
    await act(async () => vi.advanceTimersByTimeAsync(350))
    expect(animate).toHaveBeenCalledWith(
      [{ transform: 'translateX(0)' }, { transform: 'translateX(-100px)' }],
      { duration: 100 / 42 * 1000, easing: 'linear', fill: 'forwards' }
    )
    expect(label.classList.contains('ds-sidebar-title-fade')).toBe(false)
    await act(async () => header.dispatchEvent(new MouseEvent('mouseout', { bubbles: true, relatedTarget: document.body })))
    expect(label.classList.contains('ds-sidebar-title-fade')).toBe(true)
  } finally {
    await act(async () => root.unmount())
    container.remove()
    vi.useRealTimers()
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    if (originalAnimate) Object.defineProperty(HTMLElement.prototype, 'animate', originalAnimate)
    else Reflect.deleteProperty(HTMLElement.prototype, 'animate')
  }
})
