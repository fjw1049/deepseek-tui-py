// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import { Sidebar } from './Sidebar'
import { useChatStore } from '../../store/chat-store'
import type { NormalizedThread } from '../../agent/types'

vi.mock('../../store/chat-store', async () => {
  const { create } = await import('zustand')
  return { useChatStore: create((set) => ({
    route: 'channels', threads: [], activeThreadId: null, pinnedThreadIds: [], blocks: [],
    hiddenWorkspacePaths: [], sidebarLabelColors: {}, watchTurnCompletion: {}, unreadThreadIds: {},
    workspaceRoot: '/project', projectsCollapsed: true, chatsCollapsed: true, pinnedCollapsed: true,
    refreshThreads: async () => {},
    setRoute: (route: string) => set({ route }),
    setProjectsCollapsed: (projectsCollapsed: boolean) => set({ projectsCollapsed }),
    setChatsCollapsed: (chatsCollapsed: boolean) => set({ chatsCollapsed }),
    setPinnedCollapsed: (pinnedCollapsed: boolean) => set({ pinnedCollapsed })
  })) }
})
vi.mock('react-i18next', async (importOriginal) => ({ ...await importOriginal<typeof import('react-i18next')>(), useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'en' } }) }))
vi.mock('../../hooks/use-thread-tasks', () => ({
  useThreadsWithActiveTasks: () => ({ threadIds: new Set(), taskIds: new Set() })
}))
vi.mock('./ConversationSearchModal', () => ({ ConversationSearchModal: () => null }))
vi.mock('./EmptyHomeLayoutToggle', () => ({ EmptyHomeLayoutToggle: () => null }))
vi.mock('./ThemeToggle', () => ({ ThemeToggle: () => null }))
vi.mock('../settings/SettingsSidebarNav', () => ({ SettingsSidebarNav: () => null }))
globalThis.IS_REACT_ACT_ENVIRONMENT = true

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

it.each(['project', 'chats', 'pinned'])('reveals a %s conversation from activity, including the already active conversation', async (section) => {
  localStorage.removeItem('deepseekgui.sidebar.dismissedActivity')
  const thread: NormalizedThread = { id: 'target', title: 'Target conversation',
    workspace: section === 'chats' ? '' : '/project', updatedAt: '', model: '', mode: '', latestTurnStatus: 'failed' }
  useChatStore.setState({ route: 'channels', threads: [thread], activeThreadId: thread.id,
    pinnedThreadIds: section === 'pinned' ? [thread.id] : [],
    projectsCollapsed: true, chatsCollapsed: true, pinnedCollapsed: true })
  const frames = new Map<number, FrameRequestCallback>()
  let frameId = 0
  vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback) => { frames.set(++frameId, cb); return frameId })
  vi.stubGlobal('cancelAnimationFrame', (id: number) => frames.delete(id))
  vi.spyOn(window, 'matchMedia').mockReturnValue({ matches: false } as MediaQueryList)
  vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(200)
  const scroll = vi.spyOn(HTMLElement.prototype, 'scrollBy').mockImplementation(() => {})
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
    return (this.hasAttribute('data-thread-id') ? { top: 300, bottom: 340, height: 40 }
      : { top: 0, bottom: 200, height: 200 }) as DOMRect
  })
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  const noop = vi.fn()
  let request: { threadId: string | null } | null = null
  const render = () => root.render(createElement(Sidebar, {
    threads: [thread], activeThreadId: thread.id, runtimeReady: true, revealRequest: request,
    onSelectThread: (id) => { useChatStore.getState().setRoute('chat'); request = { threadId: id }; render() },
    onNewChat: () => { useChatStore.getState().setRoute('chat'); request = { threadId: null }; render() },
    onNewChatsThread: noop, onNewChatInWorkspace: noop, onOpenThreadTerminal: noop,
    onDeleteThread: noop, onArchiveThread: noop, onOpenSettings: noop, onCollapseSidebar: noop
  }))
  const flushFrames = () => { const pending = [...frames.values()]; frames.clear(); pending.forEach((cb) => cb(0)) }
  try {
    await act(async () => render())
    await act(async () => container.querySelector<HTMLButtonElement>('[aria-controls="sidebar-activity"]')!.click())
    expect(container.querySelector<HTMLElement>('.ds-sidebar-middle')!.style.display).toBe('none')
    await act(async () => container.querySelector<HTMLButtonElement>('.ds-activity-row')!.click())
    await act(async () => flushFrames())
    expect(container.querySelector<HTMLElement>('.ds-sidebar-middle')!.style.display).toBe('')
    expect(container.querySelector('.ds-activity-row')).toBeNull()
    expect(container.querySelector('[data-thread-id="target"] button[aria-current="page"]')).not.toBeNull()
    expect(container.querySelector('.ds-sidebar-link--active')).toBeNull()
    expect(scroll).toHaveBeenCalledWith({ top: 140, behavior: 'smooth' })

    if (section === 'project') {
      await act(async () => container.querySelector<HTMLButtonElement>('.ds-sidebar-workspace button')!.click())
      expect(container.querySelector('[data-thread-id="target"]')).toBeNull()
    }

    // A new-chat request returns immediately; its result can reveal a reused thread.
    await act(async () => container.querySelector<HTMLButtonElement>('[aria-controls="sidebar-activity"]')!.click())
    await act(async () => container.querySelector<HTMLButtonElement>('.ds-sidebar-link--action')!.click())
    expect(container.querySelector('.ds-activity-row')).toBeNull()
    scroll.mockClear()
    vi.spyOn(window, 'matchMedia').mockReturnValue({ matches: true } as MediaQueryList)
    await act(async () => { request = { threadId: thread.id }; render() })
    await act(async () => flushFrames())
    expect(scroll).toHaveBeenCalledWith({ top: 140, behavior: 'instant' })
    expect(container.querySelector('[data-thread-id="target"]')).not.toBeNull()

    scroll.mockClear()
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ top: 0, bottom: 200, height: 200 } as DOMRect)
    await act(async () => { request = { threadId: thread.id }; render() })
    await act(async () => flushFrames())
    expect(scroll).not.toHaveBeenCalled()

    // Superseded navigation must not run a stale scroll on the next frame.
    await act(async () => { request = { threadId: thread.id }; render() })
    await act(async () => { request = { threadId: null }; render() })
    expect(frames.size).toBe(0)

    await act(async () => container.querySelector<HTMLButtonElement>('[aria-controls="sidebar-activity"]')!.click())
    await act(async () => container.querySelector<HTMLButtonElement>('.ds-activity-row')!.dispatchEvent(
      new KeyboardEvent('keydown', { bubbles: true, key: 'ArrowLeft' })))
    await act(async () => container.querySelector<HTMLButtonElement>('.ds-activity-dismiss')!.click())
    expect(container.querySelector('.ds-activity-row')).toBeNull()
    expect(container.querySelector('.ds-activity-total')!.textContent).toBe('0')
    expect(container.querySelector('.ds-activity-indicator')).toBeNull()
    expect(useChatStore.getState().threads).toEqual([thread])
    await act(async () => useChatStore.setState({ threads: [{ ...thread, updatedAt: '2026-10-12' }] }))
    expect(container.querySelector('.ds-activity-row')).toBeNull()
    await act(async () => useChatStore.setState({ threads: [{ ...thread, latestTurnStatus: 'in_progress' }] }))
    expect(container.querySelector('.ds-activity-row')).not.toBeNull()
    await act(async () => useChatStore.setState({ threads: [thread] }))
    expect(container.querySelector('.ds-activity-row')).not.toBeNull()
  } finally {
    await act(async () => root.unmount())
    container.remove()
  }
})


it.each([
  ['completed', false, false, null],
  ['failed', false, false, null],
  ['in_progress', true, false, 'waiting'],
  ['in_progress', true, true, 'waiting'],
  ['completed', false, true, 'unread'],
  ['failed', false, true, 'unread'],
  ['in_progress', false, false, 'running'],
  ['in_progress', false, true, 'running']
] as const)('shows the appropriate activity indicator for %s, waiting=%s, unread=%s', async (status, waiting, unread, indicator) => {
  localStorage.removeItem('deepseekgui.sidebar.dismissedActivity')
  const thread: NormalizedThread = { id: 'indicator-target', title: 'Conversation', workspace: '/project',
    updatedAt: '', model: '', mode: '', latestTurnStatus: status, activityWaiting: waiting }
  useChatStore.setState({ route: 'chat', threads: [thread], activeThreadId: null, pinnedThreadIds: [],
    blocks: [], busy: false, watchTurnCompletion: {}, unreadThreadIds: { [thread.id]: unread } })
  const container = document.createElement('div')
  const root = createRoot(container)
  const noop = vi.fn()
  try {
    await act(async () => root.render(createElement(Sidebar, {
      threads: [thread], activeThreadId: null, runtimeReady: true,
      onSelectThread: noop, onNewChat: noop, onNewChatsThread: noop, onNewChatInWorkspace: noop,
      onOpenThreadTerminal: noop, onDeleteThread: noop, onArchiveThread: noop,
      onOpenSettings: noop, onCollapseSidebar: noop
    })))
    const dot = container.querySelector('.ds-activity-indicator')
    if (indicator) {
      expect(dot?.classList.contains(`ds-activity-indicator--${indicator === 'waiting' ? 'running' : indicator}`)).toBe(true)
      expect(dot?.getAttribute('aria-label')).toBe(indicator === 'unread' ? 'activityUnreadBadge' : `activityStatus_${indicator}`)
    } else {
      expect(dot).toBeNull()
    }
  } finally {
    await act(async () => root.unmount())
  }
})
