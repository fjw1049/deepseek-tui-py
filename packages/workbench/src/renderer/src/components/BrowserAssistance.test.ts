// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import { respondToAssistance } from './BrowserAssistance'
import { AssistanceCard } from './BrowserAssistanceCard'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('../store/chat-store', () => ({ useChatStore: vi.fn() }))
const container = document.createElement('div')
let root: ReturnType<typeof createRoot>
afterEach(async () => { if (root) await act(async () => root.unmount()); container.remove(); vi.restoreAllMocks() })
async function mount(status: 'human' | 'pending' = 'pending', respond = vi.fn(async () => {})) {
  document.body.append(container); root = createRoot(container)
  const reveal = vi.fn()
  await act(async () => root.render(createElement(AssistanceCard, { request: { id: 'req', thread_id: 'one', reason: 'Login needed', status }, onRespond: respond, onReveal: reveal })))
  const click = async (text: string): Promise<void> => { await act(async () => { const b = [...container.querySelectorAll('button')].find(b => b.textContent?.includes(text)); expect(b).toBeTruthy(); b!.click() }) }
  return { respond, reveal, click }
}
it('takes control before revealing the browser, and prevents repeated clicks', async () => {
  let finish!: () => void
  const respond = vi.fn(() => new Promise<void>(r => { finish = r }))
  const h = await mount('pending', respond)
  await h.click('browserAssistTakeover'); await h.click('browserAssistTakeover')
  expect(respond).toHaveBeenCalledTimes(1); expect(h.reveal).not.toHaveBeenCalled()
  await act(async () => finish()); expect(h.reveal).toHaveBeenCalledOnce()
})
it('sends ignore as a distinct decision and retains errors', async () => {
  const h = await mount('pending', vi.fn(async () => { throw new Error('Disconnected') }))
  await h.click('browserAssistIgnore')
  expect(h.respond).toHaveBeenCalledWith('ignore', '')
  expect(container.querySelector('[role="alert"]')?.textContent).toBe('Disconnected')
  expect(h.reveal).not.toHaveBeenCalled()
})
it('expands information inline, validates blank input, and sends its content', async () => {
  const h = await mount(); await h.click('browserAssistInformation')
  const field = container.querySelector('textarea')!
  expect(document.activeElement).toBe(field)
  expect(container.querySelector('button[type="submit"]')?.hasAttribute('disabled')).toBe(true)
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(field, 'Use public downloads')
    field.dispatchEvent(new Event('input', { bubbles: true }))
  })
  await h.click('browserAssistSubmit')
  expect(h.respond).toHaveBeenCalledWith('information', 'Use public downloads')
})
it('returns control explicitly and shows reading state', async () => {
  const h = await mount('human'); await h.click('browserAssistContinue')
  expect(h.respond).toHaveBeenCalledWith('continue', '')
})
it('does not broadcast a successful response on HTTP failure', async () => {
  const dispatch = vi.spyOn(window, 'dispatchEvent')
  Object.defineProperty(window, 'dsGui', { configurable: true, value: { runtimeRequest: vi.fn(async () => ({ ok: false, status: 409, body: '{"detail":"Request ended"}' })) } })
  await expect(respondToAssistance('thread/one', 'old', 'ignore')).rejects.toThrow('Request ended')
  expect(dispatch).not.toHaveBeenCalled()
})
