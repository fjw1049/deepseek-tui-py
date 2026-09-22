// @vitest-environment happy-dom
import { beforeEach, expect, it, vi } from 'vitest'
vi.mock('../i18n', () => ({ default: { t: (key: string) => key } }))
vi.mock('../agent/registry', () => ({ getProvider: vi.fn() }))
import { createConversationInSplit } from './chat-split-navigation'
import { useChatStore } from '../store/chat-store'
import { useChatLayoutStore } from '../store/chat-layout-store'

const original = useChatStore.getState()
beforeEach(() => {
  useChatStore.setState({ ...original, route: 'chat', runtimeConnection: 'ready', activeThreadId: 'a',
    threads: [{ id: 'a', title: 'A', workspace: '/repo', model: 'test', mode: 'agent', updatedAt: '' }] }, true)
  useChatLayoutStore.setState({ layouts: {}, activeLayoutKey: null })
})

it('preserves the current pane and forces a new conversation in its project', async () => {
  const createThread = vi.fn(async () => {
    expect(useChatLayoutStore.getState().layouts['/repo'].panes.map(p => p.threadId)).toEqual(['a', null])
    useChatStore.setState({ activeThreadId: 'new' })
  })
  useChatStore.setState({ createThread })
  await createConversationInSplit()
  expect(createThread).toHaveBeenCalledWith({ workspaceRoot: '/repo', forceNew: true })
  const layout = useChatLayoutStore.getState().layouts['/repo']
  expect(layout.panes.map(p => p.threadId)).toEqual(['a', 'new'])
  expect(layout.panes.find(p => p.id === layout.focused)?.threadId).toBe('new')
})

it('adds to an existing mixed-project layout using the active conversation’s project', async () => {
  useChatLayoutStore.getState().add('/other-project', 'b', 'a')
  const createThread = vi.fn(async () => { useChatStore.setState({ activeThreadId: 'new' }) })
  useChatStore.setState({ createThread })
  await createConversationInSplit()
  expect(createThread).toHaveBeenCalledWith({ workspaceRoot: '/repo', forceNew: true })
  expect(useChatLayoutStore.getState().layouts['/other-project'].panes.map(p => p.threadId)).toEqual(['b', 'a', 'new'])
})

it('does not create a conversation when six panes are already open', async () => {
  for (const id of ['b', 'c', 'd', 'e', 'f']) useChatLayoutStore.getState().add('/repo', 'a', id)
  const createThread = vi.fn()
  useChatStore.setState({ createThread })
  await createConversationInSplit()
  expect(createThread).not.toHaveBeenCalled()
  expect(useChatStore.getState().error).toBe('common:splitLimit')
})

it('ignores repeated requests during creation and removes the reservation on failure', async () => {
  let finish!: () => void
  const createThread = vi.fn(() => new Promise<void>(resolve => { finish = resolve }))
  useChatLayoutStore.getState().add('/repo', 'a', 'b')
  const before = useChatLayoutStore.getState().layouts['/repo']
  useChatStore.setState({ createThread })
  const first = createConversationInSplit()
  await createConversationInSplit()
  expect(createThread).toHaveBeenCalledOnce()
  finish()
  await first
  expect(useChatLayoutStore.getState().layouts['/repo']).toEqual(before)
})

it('does not create a split outside the main chat or without a connection', async () => {
  const createThread = vi.fn()
  useChatStore.setState({ createThread, route: 'settings' })
  await createConversationInSplit()
  useChatStore.setState({ route: 'chat', runtimeConnection: 'offline' })
  await createConversationInSplit()
  expect(createThread).not.toHaveBeenCalled()
  expect(useChatLayoutStore.getState().layouts).toEqual({})
})
