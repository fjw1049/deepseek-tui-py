// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import { BrowserAssistance } from './BrowserAssistance'
import { PendingDecisionPanel } from './chat/PendingDecisionPanel'
import { useBrowserAssistanceStore } from '../store/browser-assistance-store'
import type { ChatBlock } from '../agent/types'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
const state = vi.hoisted(() => ({ activeThreadId: 'one' as string | null }))
const t = vi.hoisted(() => (key: string) => key)
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t }) }))
vi.mock('../store/chat-store', () => ({ useChatStore: Object.assign((selector: (s: typeof state) => unknown) => selector(state), { getState: () => ({ selectThread: vi.fn(async () => {}) }) }) }))
let root: ReturnType<typeof createRoot>
let panelRoot: ReturnType<typeof createRoot>
let host: HTMLDivElement
let shell: HTMLDivElement
async function mount(items: unknown[], blocks: ChatBlock[] = []) {
  vi.useFakeTimers()
  const request = vi.fn(async () => ({ ok: true, status: 200, body: JSON.stringify({ items }) }))
  const notify = vi.fn(async () => ({ ok: true, shown: true }))
  Object.defineProperty(window, 'dsGui', { configurable: true, value: { runtimeRequest: request, showTurnCompleteNotification: notify } })
  host = document.createElement('div'); shell = document.createElement('div'); document.body.append(host, shell); root = createRoot(shell)
  panelRoot = createRoot(host)
  await act(async () => { root.render(createElement(BrowserAssistance, { visible: true, enabled: true })); panelRoot.render(createElement(PendingDecisionPanel, { blocks })) })
  return { request, notify }
}
afterEach(async () => { if (root) await act(async () => root.unmount()); if (panelRoot) await act(async () => panelRoot.unmount()); useBrowserAssistanceStore.setState({ items: [], connectionError: '', revision: 0 }); host?.remove(); shell?.remove(); state.activeThreadId = 'one'; vi.useRealTimers() })
it('notifies once while the browser is collapsed and keeps the current request visible', async () => {
  const h = await mount([{ id: 'r', thread_id: 'one', reason: 'Login needed', status: 'pending' }])
  expect(host.textContent).toContain('Login needed')
  await act(async () => vi.advanceTimersByTimeAsync(4500))
  expect(h.notify).toHaveBeenCalledTimes(1)
  expect(h.notify).toHaveBeenCalledWith(expect.objectContaining({ kind: 'browser-assistance', threadId: 'one' }))
  h.request.mockRejectedValue(new Error('Offline'))
  await act(async () => vi.advanceTimersByTimeAsync(1500))
  expect(host.textContent).toContain('Login needed')
  expect(host.textContent).toContain('browserAssistConnection')
})
it('surfaces background requests without putting their controls into the current chat', async () => {
  await mount([{ id: 'r', thread_id: 'other', reason: 'Private task detail', status: 'pending' }])
  expect(shell.textContent).toContain('browserAssistBackground')
  expect(host.textContent).not.toContain('Private task detail')
})
it('does not show another chat request in a new empty chat', async () => {
  state.activeThreadId = null
  await mount([])
  expect(host.textContent).toBe('')
})

it('shares the tool approval queue and preserves assistance drafts through selection and collapse', async () => {
  const h = await mount([{ id: 'help', thread_id: 'one', reason: 'Login needed', status: 'pending' }], [
    { kind: 'approval', id: 'approval', approvalId: 'a', summary: 'Run tests', status: 'pending' }
  ])
  const select = host.querySelector('select')!
  expect(select.options).toHaveLength(2)
  const card = host.querySelector('.ds-assistance')!
  expect(card.closest('[hidden]')).not.toBeNull()
  await act(async () => { select.value = 'browser-assistance:help'; select.dispatchEvent(new Event('change', { bubbles: true })) })
  expect(card.closest('[hidden]')).toBeNull()
  await act(async () => [...card.querySelectorAll('button')].find(b => b.textContent === 'browserAssistInformation')!.click())
  const field = card.querySelector('textarea')!
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(field, 'Use the public page')
    field.dispatchEvent(new Event('input', { bubbles: true }))
    select.value = 'approval'; select.dispatchEvent(new Event('change', { bubbles: true }))
  })
  await act(async () => { select.value = 'browser-assistance:help'; select.dispatchEvent(new Event('change', { bubbles: true })) })
  expect(card.querySelector('textarea')?.value).toBe('Use the public page')
  await act(async () => host.querySelector<HTMLButtonElement>('[aria-controls]')!.click())
  expect(card.closest('[hidden]')).not.toBeNull()
  await act(async () => host.querySelector<HTMLButtonElement>('[aria-controls]')!.click())
  h.request.mockResolvedValue({ ok: true, status: 200, body: '{"items":[]}' })
  await act(async () => card.querySelector<HTMLButtonElement>('button[type="submit"]')!.click())
  expect(h.request).toHaveBeenCalledWith('/v1/threads/one/browser/assistance', 'POST', JSON.stringify({ request_id: 'help', choice: 'information', text: 'Use the public page' }))
  expect(host.querySelector('.ds-assistance')).toBeNull()
  expect(host.querySelector('.ds-approval-bubble')).not.toBeNull()
})
