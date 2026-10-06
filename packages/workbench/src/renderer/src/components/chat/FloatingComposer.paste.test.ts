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

it('shows a pending stop and prevents duplicate requests until it settles', async () => {
  let finish!: () => void
  const onInterrupt = vi.fn(() => new Promise<void>((resolve) => { finish = resolve }))
  await act(async () => root.render(createElement(FloatingComposer, { ...props, busy: true, onInterrupt })))
  const stop = host.querySelector<HTMLButtonElement>('button[aria-busy]')!
  await act(async () => { stop.click(); stop.click() })
  expect(onInterrupt).toHaveBeenCalledOnce()
  expect(stop.disabled).toBe(true)
  expect(stop.getAttribute('aria-busy')).toBe('true')
  await act(async () => finish())
  expect(stop.disabled).toBe(false)
  expect(stop.getAttribute('aria-busy')).toBe('false')
})

it('does not leave the next conversation waiting for a previous stop request', async () => {
  let finish!: () => void
  const onInterrupt = vi.fn(() => new Promise<void>((resolve) => { finish = resolve }))
  await act(async () => root.render(createElement(FloatingComposer, { ...props, busy: true, onInterrupt })))
  await act(async () => host.querySelector<HTMLButtonElement>('button[aria-busy]')!.click())
  await act(async () => useChatStore.setState({ activeThreadId: 'paste-b' }))
  expect(host.querySelector<HTMLButtonElement>('button[aria-busy]')!.disabled).toBe(false)
  await act(async () => finish())
})

it('allows retrying stop after a request fails', async () => {
  const onInterrupt = vi.fn().mockRejectedValueOnce(new Error('Stop failed')).mockResolvedValue(undefined)
  await act(async () => root.render(createElement(FloatingComposer, { ...props, busy: true, onInterrupt })))
  const stop = host.querySelector<HTMLButtonElement>('button[aria-busy]')!
  await act(async () => stop.click())
  expect(stop.disabled).toBe(false)
  expect(useChatStore.getState().error).toBe('Stop failed')
  await act(async () => stop.click())
  expect(onInterrupt).toHaveBeenCalledTimes(2)
})
