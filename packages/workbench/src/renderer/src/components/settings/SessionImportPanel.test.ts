// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { SessionImportPanel } from './SessionImportPanel'
const state = { refreshThreads: vi.fn().mockResolvedValue(undefined) }
vi.mock('../../store/chat-store', () => ({ useChatStore: (select: (s: typeof state) => unknown) => select(state) }))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'en' } }) }))
globalThis.IS_REACT_ACT_ENVIRONMENT = true
let root: Root
let container: HTMLDivElement
const request = vi.fn()
const picker = vi.fn()
const session = (id: string, extra = {}) => ({ id, source: 'codex', path: `/source/${id}.jsonl`, title: `Conversation ${id}`, workspace: '/projects/example', workspace_available: true, archived: false, model: 'old-model', message_count: 2, updated_at: '2026-09-01T00:00:00Z', warnings: [], imported_thread_id: null, history_only: false, ...extra })
const response = (body: unknown, ok = true) => ({ ok, status: ok ? 200 : 400, body: JSON.stringify(body) })
let rows = [session('a'), session('b'), session('archived', { archived: true })]
beforeEach(async () => {
  vi.clearAllMocks()
  rows = [session('a'), session('b'), session('archived', { archived: true })]
  request.mockImplementation(async (path: string, _method: string, body: string) => {
    const payload = JSON.parse(body)
    if (path.endsWith('/scan')) return response({ root: '/source', available: true, sessions: payload.source === 'codex' ? rows : [], errors: [] })
    return response({ status: 'imported', thread_id: `imported-${payload.session_id}`, warnings: [] })
  })
  vi.stubGlobal('dsGui', { runtimeRequest: request, pickWorkspaceDirectory: picker })
  container = document.createElement('div'); document.body.append(container); root = createRoot(container)
  await act(async () => root.render(createElement(SessionImportPanel)))
})
afterEach(async () => { await act(async () => root.unmount()); container.remove(); vi.unstubAllGlobals() })
const button = (label: string) => [...container.querySelectorAll('button')].find(b => b.textContent === label)!
async function click(label: string) { await act(async () => button(label).click()) }
async function prepare() { await click('sessionImport.scan'); await click('sessionImport.selectAll') }
const imports = () => request.mock.calls.filter(call => call[0].endsWith('/import'))
it('imports only selected visible sessions and refreshes without duplicating existing imports', async () => {
  rows.push(session('existing', { imported_thread_id: 'existing' }))
  await prepare(); await click('sessionImport.importSelected')
  expect(imports().map(call => JSON.parse(call[2]).session_id)).toEqual(['a', 'b'])
  expect(imports().every(call => JSON.parse(call[2]).root === '/source')).toBe(true)
  expect(state.refreshThreads).toHaveBeenCalledOnce()
  expect(button('sessionImport.importSelected').disabled).toBe(true)
})
it('continues after a failed session and retries only the failed one', async () => {
  const standard = request.getMockImplementation()!
  let first = true
  request.mockImplementation(async (...args: [string, string, string]) => {
    if (args[0].endsWith('/import') && JSON.parse(args[2]).session_id === 'a' && first) { first = false; return response({ detail: 'Read failed' }, false) }
    return standard(...args)
  })
  await prepare(); await click('sessionImport.importSelected')
  expect(imports()).toHaveLength(2)
  expect(container.querySelector('[role="alert"]')?.textContent).toContain('Read failed')
  await click('sessionImport.retry')
  expect(imports().map(call => JSON.parse(call[2]).session_id)).toEqual(['a', 'b', 'a'])
})
it('stops after the in-flight session and retains its committed result', async () => {
  let finish!: (value: unknown) => void
  const standard = request.getMockImplementation()!
  request.mockImplementation((...args: [string, string, string]) => args[0].endsWith('/import') ? new Promise(resolve => { finish = resolve }) : standard(...args))
  await prepare(); await click('sessionImport.importSelected')
  expect(imports()).toHaveLength(1)
  await click('sessionImport.stop')
  await act(async () => finish(response({ status: 'imported', thread_id: 'imported-a', warnings: [] })))
  expect(imports()).toHaveLength(1)
  expect(state.refreshThreads).toHaveBeenCalledOnce()
  expect(button('sessionImport.importSelected').disabled).toBe(false)
})
it('relinks a history-only import after choosing a replacement folder', async () => {
  rows = [session('a', { workspace_available: false, imported_thread_id: 'imported-a', history_only: true })]
  picker.mockResolvedValue({ path: '/projects/moved', canceled: false })
  await click('sessionImport.scan'); await click('sessionImport.selectAll')
  expect(button('sessionImport.importSelected').disabled).toBe(true)
  await click('sessionImport.browse'); await click('sessionImport.selectAll'); await click('sessionImport.importSelected')
  expect(JSON.parse(imports()[0][2]).workspace).toBe('/projects/moved')
})
