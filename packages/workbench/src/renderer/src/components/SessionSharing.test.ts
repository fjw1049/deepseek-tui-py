// @vitest-environment happy-dom
import { act, createElement, StrictMode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { SessionSharing, SharedLinkReceiver } from './SessionSharing'

const state = { activeThreadId: 'company-thread', busy: false, refreshThreads: vi.fn(), selectThread: vi.fn() }
vi.mock('../store/chat-store', () => ({ useChatStore: (select: (s: typeof state) => unknown) => select(state) }))
vi.mock('react-i18next', () => {
  const t = (key: string) => key
  return { useTranslation: () => ({ t }) }
})
globalThis.IS_REACT_ACT_ENVIRONMENT = true
let root: Root
let container: HTMLDivElement
const request = vi.fn()
const clipboard = vi.fn()
const picker = vi.fn()
const preview = { title: 'Company work', created_at: '2026-09-01T00:00:00Z', turn_count: 2, model: 'deepseek-chat', files: [], messages: [], project_commit: null }

beforeEach(async () => {
  vi.clearAllMocks()
  state.busy = false
  vi.stubGlobal('dsGui', { runtimeRequest: request, pickWorkspaceDirectory: picker })
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: clipboard } })
  request.mockImplementation(async (path: string) => ({ ok: true, status: 200, body: JSON.stringify(
    path.endsWith('settings') ? { service_url: 'https://shares.test', has_upload_key: true, ready: true } :
    path.endsWith('shares') ? { url: 'https://shares.test/s/example' } :
    path.endsWith('preview') ? preview : { id: 'home-thread' }
  ) }))
  container = document.createElement('div'); document.body.append(container)
  root = createRoot(container)
  await act(async () => root.render(createElement(SessionSharing)))
})
afterEach(async () => { await act(async () => root.unmount()); container.remove(); vi.unstubAllGlobals() })
function button(label: string): HTMLButtonElement {
  const result = [...document.querySelectorAll('button')].find(b => b.textContent === label || b.getAttribute('aria-label') === label)
  if (!result) throw new Error(`Missing button: ${label}`)
  return result
}
async function click(label: string) { await act(async () => button(label).click()) }
async function paste(value: string) {
  const el = document.querySelector<HTMLInputElement>('input[aria-label="sharing.link"]')!
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(el, value)
    el.dispatchEvent(new Event('input', { bubbles: true }))
  })
}
it('creates and copies a link in one action without configuration fields', async () => {
  await click('sharing.open'); await click('sharing.copy')
  expect(request).toHaveBeenCalledWith('/v1/sharing/shares', 'POST', JSON.stringify({ thread_id: 'company-thread', include_project: false, expires_in_days: 7 }))
  expect(clipboard).toHaveBeenCalledWith('https://shares.test/s/example')
  expect(document.querySelector('input[type="password"]')).toBeNull()
  expect(document.querySelector('select')).toBeNull()
  await click('sharing.copy')
  expect(request.mock.calls.filter(call => call[0].endsWith('/shares'))).toHaveLength(1)
  await click('sharing.revoke')
  expect(request).toHaveBeenCalledWith('/v1/sharing/revoke', 'POST', JSON.stringify({ url: 'https://shares.test/s/example' }))
})
it('continues a conversation with only a link, without settings or a directory', async () => {
  await click('sharing.open'); await click('sharing.openLink'); await paste('https://shares.test/s/example')
  await click('sharing.openConversation'); await click('sharing.continueSimple')
  expect(request).toHaveBeenCalledWith('/v1/sharing/restore', 'POST', JSON.stringify({ url: 'https://shares.test/s/example', restore_project: true }))
  expect(request.mock.calls.some(call => call[1] === 'PUT')).toBe(false)
  expect(picker).not.toHaveBeenCalled()
  expect(state.selectThread).toHaveBeenCalledWith('home-thread')
})
it('asks for a folder only when restoring file changes', async () => {
  request.mockImplementation(async (path: string) => ({ ok: true, status: 200, body: JSON.stringify(
    path.endsWith('preview') ? { ...preview, project_commit: 'a'.repeat(40) } : { id: 'home-thread' }
  ) }))
  picker.mockResolvedValue({ path: '/home/project', canceled: false })
  await act(async () => root.render(createElement(SessionSharing, { key: 'incoming', incomingUrl: 'https://shares.test/s/example' })))
  await click('sharing.continueSimple')
  expect(picker).toHaveBeenCalledOnce()
  expect(request).toHaveBeenCalledWith('/v1/sharing/restore', 'POST', JSON.stringify({ url: 'https://shares.test/s/example', workspace: '/home/project', restore_project: true }))
})
it('explains unavailable sharing without asking the user to fill in server details', async () => {
  request.mockResolvedValue({ ok: true, status: 200, body: JSON.stringify({ service_url: '', has_upload_key: false, ready: false }) })
  await click('sharing.open')
  expect(document.body.textContent).toContain('sharing.unavailable')
  expect(document.querySelector('input')).toBeNull()
  expect(button('sharing.openLink').disabled).toBe(false)
})
it('receives a browser link and previews it without importing automatically', async () => {
  vi.stubGlobal('dsGui', { runtimeRequest: request, getSharedLink: vi.fn().mockResolvedValue('https://shares.test/s/example'), onSharedLinkAvailable: vi.fn().mockReturnValue(() => {}) })
  await act(async () => root.render(createElement(StrictMode, null, createElement(SharedLinkReceiver))))
  expect(document.body.textContent).toContain('Company work')
  expect(request.mock.calls.some(call => call[0].endsWith('/restore'))).toBe(false)
})
it('disables sharing during an active turn', async () => {
  state.busy = true; await act(async () => root.render(createElement(SessionSharing)))
  await click('sharing.open')
  expect(button('sharing.copy').disabled).toBe(true)
})
