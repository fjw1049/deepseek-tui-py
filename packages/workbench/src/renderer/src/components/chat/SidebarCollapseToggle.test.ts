// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { useChatStore } from '../../store/chat-store'
import { SidebarProjectsColumn } from './SidebarProjectsSection'
import { SidebarChatsSection } from './SidebarChatsSection'

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

it('toggles both sections from persistent header buttons and removes the overflow actions', async () => {
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  const noop = vi.fn()
  const callbacks = {
    onNewChat: noop, onSelectThread: noop, onOpenThreadTerminal: noop,
    onDeleteThread: noop, onArchiveThread: noop, onTogglePin: noop,
    t: (key: string) => key
  }
  try {
    for (const section of ['Projects', 'Chats']) {
      await act(async () => root.render(section === 'Projects'
        ? createElement(SidebarProjectsColumn, {
          ...callbacks, threads: [], activeThreadId: null, runtimeReady: true,
          workspaceRoot: '/test/project', busy: false, watchTurnCompletion: {},
          unreadThreadIds: {}, pinnedThreadIds: [], locale: 'en', onPickWorkspace: noop,
          onRemoveWorkspace: noop, onDeleteWorkspace: noop, onCreateThreadInWorkspace: noop
        })
        : createElement(SidebarChatsSection, callbacks)))
      const button = () => container.querySelector<HTMLButtonElement>(`button[aria-label="sidebar${section}CollapseAll"], button[aria-label="sidebar${section}ExpandAll"]`)!
      expect(button().className).not.toContain('opacity-0')
      expect(button().getAttribute('aria-expanded')).toBe('true')
      await act(async () => button().click())
      expect(button().getAttribute('aria-expanded')).toBe('false')
      await act(async () => button().click())
      expect(button().getAttribute('aria-expanded')).toBe('true')
      if (section === 'Projects') {
        await act(async () => useChatStore.getState().setProjectsCollapsed(true))
        await act(async () => button().click())
        expect(useChatStore.getState().projectsCollapsed).toBe(false)
        expect(button().getAttribute('aria-expanded')).toBe('true')
      }
      await act(async () => container.querySelector<HTMLButtonElement>(`button[aria-label="sidebar${section}Menu"]`)!.click())
      const menu = document.querySelector('[role="menu"]')!
      expect(menu).not.toBeNull()
      expect(menu.textContent).not.toMatch(/ExpandAll|CollapseAll/)
      await act(async () => container.querySelector<HTMLButtonElement>(`button[aria-label="sidebar${section}Menu"]`)!.click())
    }
  } finally {
    await act(async () => root.unmount())
    container.remove()
  }
})
