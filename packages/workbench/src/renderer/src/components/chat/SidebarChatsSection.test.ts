// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { SidebarChatsSection } from './SidebarChatsSection'
import { CHATS_SORT_STORAGE_KEY } from '../../lib/sidebar-chats-sort'
import { CHATS_ORDER_STORAGE_KEY } from '../../lib/sidebar-manual-order'

vi.mock('../../store/chat-store', async () => {
  const { create } = await import('zustand')
  return { useChatStore: create(() => ({
    threads: [
      { id: 'a', title: 'Alpha', workspace: '', updatedAt: '2026-01-01', createdAt: '2026-03-01' },
      { id: 'b', title: 'Beta', workspace: '', updatedAt: '2026-03-01', createdAt: '2026-01-01' },
      { id: 'c', title: 'Charlie', workspace: '', updatedAt: '2026-02-01' },
      { id: 'project', title: 'Project', workspace: '/project', updatedAt: '2026-04-01' },
      { id: 'pinned', title: 'Pinned', workspace: '', updatedAt: '2026-04-01' }
    ],
    pinnedThreadIds: ['pinned'], blocks: [], watchTurnCompletion: {}, unreadThreadIds: {},
    chatsCollapsed: false
  })) }
})
vi.mock('../../hooks/use-thread-tasks', () => ({
  useThreadsWithActiveTasks: () => ({ threadIds: new Set(), taskIds: new Set() })
}))
vi.mock('./SidebarProjectsSection', () => ({
  ThreadRow: ({ thread }: { thread: { id: string } }) => createElement('div', { 'data-thread': thread.id })
}))

it('switches and saves sorting, clears manual order, and restores the saved mode on remount', async () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  localStorage.clear()
  localStorage.setItem(CHATS_ORDER_STORAGE_KEY, JSON.stringify(['c', 'b', 'a']))
  const host = document.createElement('div')
  document.body.append(host)
  let root = createRoot(host)
  const noop = vi.fn()
  const render = () => root.render(createElement(SidebarChatsSection, {
    onNewChat: noop, onSelectThread: noop, onOpenThreadTerminal: noop,
    onDeleteThread: noop, onArchiveThread: noop, onTogglePin: noop, t: (key) => key
  }))
  const ids = () => Array.from(host.querySelectorAll('[data-thread]'), (el) => el.getAttribute('data-thread'))
  const open = async () => act(async () => host.querySelector<HTMLButtonElement>('[aria-label="sidebarChatsMenu"]')!.click())
  const choose = async (text: string) => act(async () => {
    Array.from(document.querySelectorAll<HTMLButtonElement>('[role="menu"] button'))
      .find((button) => button.textContent === text)!.click()
  })
  try {
    await act(async () => render())
    expect(ids()).toEqual(['c', 'b', 'a'])
    await open()
    expect(document.querySelectorAll('[aria-checked="true"]')).toHaveLength(0)
    await choose('sidebarProjectsSortRestoreAuto')
    expect(ids()).toEqual(['b', 'c', 'a'])
    await open()
    await choose('sidebarChatsSortNameAsc')
    expect(ids()).toEqual(['a', 'b', 'c'])
    expect(localStorage.getItem(CHATS_SORT_STORAGE_KEY)).toBe('name_asc')
    expect(JSON.parse(localStorage.getItem(CHATS_ORDER_STORAGE_KEY)!)).toEqual([])
    await open()
    await choose('sidebarProjectsSortCreated')
    expect(ids()).toEqual(['a', 'b', 'c'])
    await act(async () => root.unmount())
    root = createRoot(host)
    await act(async () => render())
    await open()
    expect(document.querySelector('[aria-checked="true"]')?.textContent).toBe('sidebarProjectsSortCreated')
    expect(ids()).toEqual(['a', 'b', 'c'])
  } finally {
    await act(async () => root.unmount())
    host.remove()
    localStorage.clear()
  }
})
