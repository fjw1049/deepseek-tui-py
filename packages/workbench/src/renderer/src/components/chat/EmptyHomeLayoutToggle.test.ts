// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { useChatStore } from '../../store/chat-store'
import { EmptyHomeLayoutToggle } from './EmptyHomeLayoutToggle'

const { loadThread, applyAppearance } = vi.hoisted(() => ({
  loadThread: vi.fn().mockResolvedValue(true), applyAppearance: vi.fn()
}))
vi.mock('../../store/chat-store', async () => {
  const { create } = await import('zustand')
  return { useChatStore: create(() => ({
    threads: [], unreadThreadIds: {}, watchTurnCompletion: {},
    activeThreadId: 'current', route: 'chat', runtimeConnection: 'ready',
    blocks: [{ kind: 'user', id: 'query', text: 'Hello' }], busy: false, liveAssistant: '', liveReasoning: ''
  })) }
})
vi.mock('../../lib/apply-appearance', () => ({
  getEmptyHomeLayout: () => 'normal', subscribeAppearance: () => () => {}, applyAppearance
}))
vi.mock('react-i18next', () => ({ useTranslation: () => ({
  t: (key: string, values?: { count: number; title: string }) => values ? `${key}: ${values.count} ${values.title}` : key
}) }))
globalThis.IS_REACT_ACT_ENVIRONMENT = true

it('opens unread completions one at a time, keeps the bell outside home and clears only its orange dot when read', async () => {
  const setSettings = vi.fn().mockResolvedValue({ appearance: { emptyHomeLayout: 'simple' } })
  Object.defineProperty(window, 'dsGui', { configurable: true, value: { setSettings } })
  const selectThread = vi.fn(async (id: string) => {
    if (!await loadThread(id)) return
    const unreadThreadIds = { ...useChatStore.getState().unreadThreadIds }
    delete unreadThreadIds[id]
    useChatStore.setState({ activeThreadId: id, unreadThreadIds })
  })
  useChatStore.setState({ selectThread, setRoute: (route) => useChatStore.setState({ route }), threads: ['current', 'first', 'second', 'running', 'watched', 'archived'].map((id) => ({
    id, title: id, mode: 'agent', model: 'test', updatedAt: '2026-09-07',
    status: id === 'running' ? 'running' : 'completed', archived: id === 'archived'
  })), unreadThreadIds: { current: false, first: true, second: true, running: true, watched: true, archived: true, missing: true },
  watchTurnCompletion: { watched: true } })
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  await act(async () => root.render(createElement(EmptyHomeLayoutToggle)))
  const button = container.querySelector('button')!
  expect(button.querySelector('.lucide-bell')).not.toBeNull()
  expect(button.title).toBe('openNextUnreadThread: 2 first')
  expect(button.querySelector('.bg-orange-500')).not.toBeNull()
  expect(button.hasAttribute('aria-pressed')).toBe(false)
  let finish!: (value: boolean) => void
  loadThread.mockImplementationOnce(() => new Promise<boolean>((resolve) => { finish = resolve }))
  await act(async () => button.click())
  expect(button.disabled).toBe(true)
  await act(async () => button.click())
  expect(selectThread).toHaveBeenCalledTimes(1)
  await act(async () => finish(true))
  expect(button.title).toBe('openNextUnreadThread: 1 second')
  expect(button.querySelector('.lucide-bell')).not.toBeNull()
  expect(setSettings).not.toHaveBeenCalled()
  loadThread.mockResolvedValueOnce(false)
  await act(async () => button.click())
  expect(useChatStore.getState().unreadThreadIds.second).toBe(true)
  expect(button.title).toBe('openNextUnreadThread: 1 second')
  await act(async () => button.click())
  expect(useChatStore.getState().activeThreadId).toBe('second')
  expect(button.querySelector('.lucide-bell')).not.toBeNull()
  expect(button.querySelector('.bg-orange-500')).toBeNull()
  expect(button.title).toBe('noUnreadThreads')
  await act(async () => button.click())
  expect(setSettings).not.toHaveBeenCalled()
  await act(async () => useChatStore.setState({ activeThreadId: null, blocks: [] }))
  expect(button.querySelector('.lucide-layout-dashboard')).not.toBeNull()
  await act(async () => button.click())
  expect(setSettings).toHaveBeenCalledExactlyOnceWith({ appearance: { emptyHomeLayout: 'simple' } })
  expect(applyAppearance).toHaveBeenCalledTimes(1)
  await act(async () => useChatStore.setState({ unreadThreadIds: { first: true } }))
  expect(button.querySelector('.lucide-layout-dashboard')).not.toBeNull()
  await act(async () => useChatStore.setState({ route: 'settings' }))
  expect(button.querySelector('.lucide-bell')).not.toBeNull()
  expect(button.querySelector('.bg-orange-500')).not.toBeNull()
  await act(async () => button.click())
  expect(useChatStore.getState().route).toBe('chat')
  expect(useChatStore.getState().activeThreadId).toBe('first')
  await act(async () => useChatStore.setState({ route: 'kanban', unreadThreadIds: {} }))
  expect(button.querySelector('.lucide-bell')).not.toBeNull()
  expect(button.querySelector('.bg-orange-500')).toBeNull()
  await act(async () => root.unmount())
  container.remove()
})
