// @vitest-environment happy-dom
import { act, createElement, type ComponentProps } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { FloatingComposer } from './FloatingComposer'
import { useChatStore } from '../../store/chat-store'
import i18n from '../../i18n'
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
  vi.stubGlobal('dsGui', { runtimeRequest: vi.fn(async () => ({ ok: true, status: 200, body: '{}' })), writePasteTextFile: vi.fn(() => new Promise(resolve => resolves.push(resolve))) })
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
})
afterEach(async () => { await act(async () => root.unmount()); host.remove(); useChatStore.setState(initial, true); vi.unstubAllGlobals(); vi.restoreAllMocks() })
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

it('shows a paused queue with a resume action instead of the auto-send hint', async () => {
  const onResumeQueuedMessages = vi.fn()
  const queuedMessages = [{ id: 'q1', text: 'follow up', mode: 'agent' as const }]
  await act(async () => root.render(createElement(FloatingComposer, { ...props, queuedMessages })))
  expect(host.querySelector('[role="status"] button')).toBeNull()
  // Rows sit on the card's control tint, not the darker shell underlay (bg-ds-main).
  expect(host.querySelector('.ds-queued-message')!.className).toContain('bg-ds-subtle')
  expect(host.querySelector('.ds-queued-message')!.className).not.toContain('bg-ds-main')
  await act(async () => root.render(createElement(FloatingComposer, {
    ...props, queuedMessages, queuePaused: true, onResumeQueuedMessages
  })))
  const resume = host.querySelector<HTMLButtonElement>('[role="status"] button')!
  expect(resume).toBeTruthy()
  await act(async () => resume.click())
  expect(onResumeQueuedMessages).toHaveBeenCalledOnce()
})

it.each([
  { supported: true, installed: true, enabled: true, visible: true },
  { supported: true, installed: true, enabled: false, visible: false },
  { supported: true, installed: false, enabled: true, visible: false },
  { supported: false, installed: true, enabled: true, visible: false },
  { visible: false }
])('lists usable built-in CUA alongside ordinary plugins: %j', async ({ visible, ...status }) => {
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({ width: 900, height: 100, x: 0, y: 0, top: 0, left: 0, right: 900, bottom: 100, toJSON: () => ({}) })
  const runtimeRequest = vi.fn(async (path: string) => {
    if (path === '/v1/cua/status') {
      if (!('supported' in status)) throw new Error('Status unavailable')
      return { ok: true, body: JSON.stringify(status) }
    }
    return { ok: true, body: JSON.stringify({ plugins: [
      { name: 'data-analysis', enabled: true, trusted: true },
      { name: 'disabled-plugin', enabled: false }
    ] }) }
  })
  vi.stubGlobal('dsGui', { runtimeRequest })
  const onSend = vi.fn().mockResolvedValue(true)
  await act(async () => root.render(createElement(FloatingComposer, { ...props, hasActiveThread: false, input: 'Open Notes', onSend })))
  await act(async () => host.querySelector<HTMLButtonElement>(`button[aria-label="${i18n.t('composerPlusMenu')}"]`)!.click())
  expect(host.querySelector('[id$="plugin-data-analysis"]')).not.toBeNull()
  expect(host.querySelector('[id$="plugin-disabled-plugin"]')).toBeNull()
  if (visible) {
    const search = host.querySelector<HTMLInputElement>(`input[placeholder="${i18n.t('composerPlusSearch')}"]`)!
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(search, 'CUA')
      search.dispatchEvent(new Event('input', { bubbles: true }))
    })
    expect(host.querySelector('[id$="plugin-data-analysis"]')).toBeNull()
  }
  const cua = Array.from(host.querySelectorAll('button')).find(button => button.id.endsWith('plugin-computer-use'))
  expect(Boolean(cua)).toBe(visible)
  if (cua) {
    await act(async () => cua.click())
    await act(async () => host.querySelector('textarea')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })))
    expect(onSend).toHaveBeenCalled()
    expect(onSend.mock.calls[0][0]).toBe(`${i18n.t('computerUseTaskPrefix')} Open Notes`)
  }
})
