// @vitest-environment happy-dom
import { act, createElement, type ComponentProps } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { FloatingComposer } from './FloatingComposer'
import { useChatStore } from '../../store/chat-store'
vi.mock('./ReasoningEffortSelector', () => ({ ReasoningEffortSelector: () => null }))
const initial = useChatStore.getState()
let host: HTMLDivElement, root: ReturnType<typeof createRoot>
let resolves: Array<(result: unknown) => void>
const noop = () => {}
const props: ComponentProps<typeof FloatingComposer> = {
  input: '', setInput: noop, mode: 'agent', setMode: noop, busy: false,
  runtimeReady: true, hasActiveThread: true, composerModel: 'test', composerPickList: [],
  onComposerModelChange: noop, queuedMessages: [], onRemoveQueuedMessage: noop,
  onWithdrawQueuedMessage: () => null, onSendQueuedMessageNow: noop,
  onSend: async () => true, onInterrupt: noop, onCompact: async () => {}, onFork: async () => {}, onOpenDiff: noop
}
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  resolves = []
  useChatStore.setState({ ...initial, activeThreadId: 'paste-a', workspaceRoot: '/repo', runtimeConnection: 'ready', refreshPendingUserInputs: async () => {} }, true)
  vi.stubGlobal('dsGui', { writePasteTextFile: vi.fn(() => new Promise(resolve => resolves.push(resolve))) })
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
})
afterEach(async () => { await act(async () => root.unmount()); host.remove(); useChatStore.setState(initial, true); vi.unstubAllGlobals() })
function paste() {
  const event = new Event('paste', { bubbles: true, cancelable: true })
  Object.defineProperty(event, 'clipboardData', { value: { files: [], getData: () => 'long paste\n'.repeat(1000) } })
  host.querySelector('textarea')!.dispatchEvent(event)
}
const result = (name: string) => ({ ok: true, relativePath: name, name, size: 100 })
it('preserves both attachments when two writes finish out of order', async () => {
  await act(async () => root.render(createElement(FloatingComposer, props)))
  await act(async () => { paste(); paste() })
  expect(resolves).toHaveLength(2)
  await act(async () => resolves[1](result('second.txt')))
  await act(async () => resolves[0](result('first.txt')))
  expect(host.textContent).toContain('second.txt')
  expect(host.textContent).toContain('first.txt')
})
it('does not add the previous conversation attachment after switching', async () => {
  await act(async () => root.render(createElement(FloatingComposer, props)))
  await act(async () => paste())
  await act(async () => useChatStore.setState({ activeThreadId: 'paste-b' }))
  await act(async () => resolves[0](result('old-chat.txt')))
  expect(host.textContent).not.toContain('old-chat.txt')
})
