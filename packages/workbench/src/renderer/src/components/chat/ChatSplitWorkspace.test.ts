// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { ComponentProps } from 'react'

const provider = vi.hoisted(() => ({
  getThreadDetail: vi.fn(async () => ({ blocks: [], latestSeq: 0, threadStatus: 'completed' })),
  subscribeThreadEvents: vi.fn(async () => {}), fetchPendingApprovals: vi.fn(async () => []),
  fetchPendingUserInputs: vi.fn(async () => []), fetchPendingElevations: vi.fn(async () => [])
}))
vi.mock('../../i18n', () => ({ default: { t: (key: string) => key } }))
vi.mock('../../agent/registry', () => ({ getProvider: () => provider }))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('./MessageTimeline', () => ({ MessageTimeline: () => null }))
vi.mock('./ComposerStage', () => ({ ComposerStage: (props: { input: string; setInput: (text: string) => void }) =>
  createElement('textarea', { value: props.input, onChange: (event: { target: { value: string } }) => props.setInput(event.target.value) })
}))
import { ChatSplitWorkspace } from './ChatSplitWorkspace'
import { useChatStore } from '../../store/chat-store'
import { resolveChatLayoutKey, useChatLayoutStore } from '../../store/chat-layout-store'
import { openThreadInSplit } from '../../lib/chat-split-navigation'
import { disposeChatPaneSessions, getChatPaneSession } from '../../store/chat-pane-sessions'

const original = useChatStore.getState()
let root: Root, container: HTMLDivElement
const threads = ['a', 'b', 'c', 'd', 'e'].map(id => ({ id, title: `Task ${id}`, workspace: id === 'a' ? '/repo' : `/repo-${id}`, model: 'test', mode: 'agent', updatedAt: '' }))
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement('div'); document.body.append(container); root = createRoot(container)
  useChatStore.setState({ ...original, threads, activeThreadId: 'a', workspaceRoot: '/repo', runtimeConnection: 'ready' }, true)
  useChatLayoutStore.setState({ layouts: {}, activeLayoutKey: null })
  const actions = useChatLayoutStore.getState()
  actions.add('/repo', 'a', 'b'); actions.add('/repo', 'a', 'c'); actions.add('/repo', 'a', 'd')
})
afterEach(() => { act(() => root.unmount()); container.remove(); disposeChatPaneSessions(); useChatStore.setState(original, true); vi.restoreAllMocks() })

function Harness() {
  const layout = useChatLayoutStore(state => state.layouts['/repo'])
  return createElement(ChatSplitWorkspace, { project: '/repo', layout, getInitialDraft: id => `draft-${id}`,
    onFocus: () => {}, onOpenFile: () => {}, onOpenDiff: () => {} } satisfies ComponentProps<typeof ChatSplitWorkspace>)
}

it('renders exactly four independent composers, disables adding, and preserves the surviving DOM when closing', async () => {
  await act(async () => root.render(createElement(Harness)))
  expect(container.querySelectorAll('[data-chat-pane]')).toHaveLength(4)
  const inputs = [...container.querySelectorAll('textarea')]
  expect(inputs.map(input => input.value)).toEqual(['draft-a', 'draft-b', 'draft-c', 'draft-d'])
  const addButtons = [...container.querySelectorAll<HTMLButtonElement>('button[aria-label="splitAdd"]')]
  expect(addButtons).toHaveLength(4)
  expect(addButtons.every(button => button.disabled)).toBe(true)
  const firstStore = getChatPaneSession('a').store
  await act(async () => container.querySelector<HTMLButtonElement>('button[aria-label="splitClose"]')!.click())
  expect(container.querySelectorAll('[data-chat-pane]')).toHaveLength(3)
  expect(container.querySelector('textarea')).toBe(inputs[1])
  expect(getChatPaneSession('a').store).toBe(firstStore) // closing a view does not stop its runtime
  expect(getChatPaneSession('a').draft).toBe('draft-a')
})

it('adjusts split ratios by keyboard and keeps task navigation outside the scoped runtime', async () => {
  const selectThread = vi.fn(async () => {})
  const forkThread = vi.fn(async () => {})
  useChatStore.setState({ selectThread, forkThread })
  await act(async () => root.render(createElement(Harness)))
  const separator = container.querySelector('[role="separator"][aria-orientation="vertical"]')!
  await act(async () => separator.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true })))
  expect(useChatLayoutStore.getState().layouts['/repo'].x).toBe(.55)
  const pane = getChatPaneSession('a')
  await pane.store.getState().selectThread('e')
  await pane.store.getState().forkThread('a', 'message-a')
  expect(selectThread).toHaveBeenCalledWith('e')
  expect(forkThread).toHaveBeenCalledWith('a', 'message-a')
  expect(pane.store.getState().activeThreadId).toBe('a')
})


it('keeps the surviving session as the command owner after returning to a single conversation', async () => {
  await act(async () => root.render(createElement(Harness)))
  const session = getChatPaneSession('a')
  const interrupt = vi.fn(async () => { session.store.setState({ busy: false }) })
  const sendMessage = vi.fn(async () => true)
  const queue = [{ id: 'queued-a', text: 'Continue A' }]
  await act(async () => session.store.setState({ busy: true, currentTurnId: 'turn-a', queuedMessages: queue,
    composerModel: 'model-a', interrupt, sendMessage }))
  expect(useChatStore.getState()).toMatchObject({ activeThreadId: 'a', busy: true, queuedMessages: queue, composerModel: 'model-a' })
  const actions = useChatLayoutStore.getState()
  for (const pane of actions.layouts['/repo'].panes.filter(p => p.threadId !== 'a')) {
    await act(async () => actions.close('/repo', pane.id))
  }
  expect(useChatLayoutStore.getState().layouts['/repo'].panes).toHaveLength(1)
  expect(getChatPaneSession('a')).toBe(session)
  expect(session.draft).toBe('draft-a')
  await act(async () => { await useChatStore.getState().interrupt(); await useChatStore.getState().sendMessage('single view') })
  expect(interrupt).toHaveBeenCalledOnce()
  expect(sendMessage).toHaveBeenCalledWith('single view')
  expect(useChatStore.getState().busy).toBe(false)
})


it('keeps cross-project navigation in the same layout and each session in its own workspace', async () => {
  useChatLayoutStore.setState({ layouts: {}, activeLayoutKey: null })
  useChatStore.setState({ selectThread: async id => { useChatStore.setState({ activeThreadId: id }) } })
  expect(openThreadInSplit('b')).toBe(true)
  expect(resolveChatLayoutKey(useChatLayoutStore.getState(), '/repo-b')).toBe('/repo')
  expect(openThreadInSplit('c')).toBe(true)
  expect(openThreadInSplit('d')).toBe(true)
  expect(openThreadInSplit('e')).toBe(false)
  await act(async () => root.render(createElement(Harness)))
  expect(container.querySelectorAll('[data-chat-pane]')).toHaveLength(4)
  for (const thread of threads.slice(0, 4)) {
    expect(getChatPaneSession(thread.id).store.getState().workspaceRoot).toBe(thread.workspace)
    expect(container.querySelector(`.ds-chat-split-project[title="${thread.workspace}"]`)).not.toBeNull()
  }
  const before = useChatLayoutStore.getState().layouts['/repo'].panes
  await act(async () => { expect(openThreadInSplit('a')).toBe(true) })
  expect(useChatLayoutStore.getState().layouts['/repo'].panes).toEqual(before)
  expect(useChatStore.getState().activeThreadId).toBe('a')
  await act(async () => { expect(openThreadInSplit('e', 'right', before[1].id)).toBe(true) })
  expect(useChatLayoutStore.getState().layouts['/repo'].panes.map(p => p.threadId)).toEqual(['a', 'e', 'c', 'd'])
  expect(getChatPaneSession('e').store.getState().workspaceRoot).toBe('/repo-e')
})

it('offers tasks from other projects in an empty pane', async () => {
  useChatLayoutStore.setState({ layouts: {}, activeLayoutKey: null })
  useChatLayoutStore.getState().add('/repo', 'a')
  await act(async () => root.render(createElement(Harness)))
  const options = [...container.querySelectorAll('option')]
  expect(options.some(option => option.value === 'b' && option.textContent?.includes('repo-b'))).toBe(true)
})
