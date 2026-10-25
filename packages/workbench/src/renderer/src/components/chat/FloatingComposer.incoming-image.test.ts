// @vitest-environment happy-dom
import { act, createElement, type ComponentProps } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { FloatingComposer } from './FloatingComposer'
import { useChatStore } from '../../store/chat-store'
import { WORKSPACE_FILE_PREVIEW_EVENT } from '../../lib/workspace-file-preview'
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

it('opens the attached image from anywhere on its card except the remove button', async () => {
  await act(async () => root.render(createElement(FloatingComposer, { ...props, incomingImage: image(vi.fn()) })))
  await vi.waitFor(() => expect(host.textContent).toContain('browser-annotation.png'))
  const opened = vi.fn()
  window.addEventListener(WORKSPACE_FILE_PREVIEW_EVENT, opened)
  try {
    const badge = [...host.querySelectorAll('span')].find((span) => span.textContent === 'PNG')!
    const remove = badge.parentElement!.querySelector<HTMLButtonElement>('button:not(.ds-file-chip)')!
    await act(async () => badge.click())
    expect(opened).toHaveBeenCalledTimes(1)
    expect((opened.mock.calls[0][0] as CustomEvent).detail).toEqual({ path: 'shot.png', workspaceRoot: '/repo' })
    await act(async () => remove.click())
    expect(opened).toHaveBeenCalledTimes(1)
    expect(host.textContent).not.toContain('browser-annotation.png')
  } finally {
    window.removeEventListener(WORKSPACE_FILE_PREVIEW_EVENT, opened)
  }
})

it('tells the browser pane the image was not attached when there is no workspace', async () => {
  useChatStore.setState({ activeThreadId: null, workspaceRoot: '' })
  const settle = vi.fn()
  await act(async () => root.render(createElement(FloatingComposer, { ...props, hasActiveThread: false, incomingImage: image(settle) })))
  expect(settle).toHaveBeenCalledWith(false)
  expect(window.dsGui.writePasteImageFile).not.toHaveBeenCalled()
})
