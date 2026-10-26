// @vitest-environment happy-dom
import { act, createElement, type ComponentProps } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { FloatingComposer } from './FloatingComposer'
import { useChatStore } from '../../store/chat-store'
import { useBrowserDemoStore } from '../../store/browser-demo-store'
vi.mock('./ReasoningEffortSelector', () => ({ ReasoningEffortSelector: () => null }))
const initial = useChatStore.getState()
let host: HTMLDivElement, root: ReturnType<typeof createRoot>
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
  useChatStore.setState({ ...initial, activeThreadId: 'demo-a', workspaceRoot: '/repo', runtimeConnection: 'ready', refreshPendingUserInputs: async () => {} }, true)
  useBrowserDemoStore.setState({ active: {}, request: null })
  // happy-dom lays nothing out; give the footer a roomy chat width.
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue(new DOMRect(0, 0, 720, 40))
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
})
afterEach(async () => { await act(async () => root.unmount()); host.remove(); useChatStore.setState(initial, true); vi.restoreAllMocks() })

it('keeps demonstration controls out of the composer, including while recording', async () => {
  await act(async () => root.render(createElement(FloatingComposer, props)))
  expect(host.querySelector('[data-composer-browser-demo]')).toBeNull()
  await act(async () => useBrowserDemoStore.setState({ active: { 'demo-a': true } }))
  expect(host.querySelector('[data-composer-browser-demo]')).toBeNull()
  expect(useBrowserDemoStore.getState().request).toBeNull()
})

it('has no demonstrate button without a conversation', async () => {
  useChatStore.setState({ activeThreadId: null })
  await act(async () => root.render(createElement(FloatingComposer, { ...props, hasActiveThread: false })))
  expect(host.querySelector('[data-composer-browser-demo]')).toBeNull()
})
