// @vitest-environment happy-dom
import { act, createElement, type ComponentProps } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { FloatingComposer } from './FloatingComposer'
import { useChatStore } from '../../store/chat-store'
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
  useChatStore.setState({ ...initial, activeThreadId: 'img-a', workspaceRoot: '/repo', runtimeConnection: 'ready', refreshPendingUserInputs: async () => {} }, true)
  vi.stubGlobal('dsGui', { writePasteImageFile: vi.fn(async () => ({ ok: true, relativePath: 'shot.png', name: 'shot.png', size: 3 })) })
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
})
afterEach(async () => { await act(async () => root.unmount()); host.remove(); useChatStore.setState(initial, true); vi.unstubAllGlobals(); vi.restoreAllMocks() })
const image = (settle: (attached: boolean) => void) =>
  ({ id: 1, file: new File(['png'], 'browser-annotation.png', { type: 'image/png' }), settle })

it('tells the browser pane the image was attached', async () => {
  const settle = vi.fn()
  await act(async () => root.render(createElement(FloatingComposer, { ...props, incomingImage: image(settle) })))
  await vi.waitFor(() => expect(settle).toHaveBeenCalledWith(true))
  expect(host.textContent).toContain('browser-annotation.png')
})

it('tells the browser pane the image was not attached when there is no workspace', async () => {
  useChatStore.setState({ activeThreadId: null, workspaceRoot: '' })
  const settle = vi.fn()
  await act(async () => root.render(createElement(FloatingComposer, { ...props, hasActiveThread: false, incomingImage: image(settle) })))
  expect(settle).toHaveBeenCalledWith(false)
  expect(window.dsGui.writePasteImageFile).not.toHaveBeenCalled()
})
