// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ChatStoreContext, createChatSessionStore } from '../store/chat-store'
import type { ChatState } from '../store/chat-store-types'
import { resolvePetSpritesheetSrc } from '../lib/pet/pet-catalog'
import { emitPetEvent } from '../lib/pet/pet-events'
import { readPetSlug, writePetSlug } from '../lib/pet/pet-preferences'
import { usePetController } from './use-pet-controller'

vi.mock('../lib/pet/pet-catalog', () => ({ resolvePetSpritesheetSrc: vi.fn() }))

const sessions: ReturnType<typeof createChatSessionStore>[] = []
const snapshots: Record<string, ReturnType<typeof usePetController>> = {}
let root: ReturnType<typeof createRoot>
function Probe({ id }: { id: string }) { snapshots[id] = usePetController(); return null }
function session(patch: Partial<ChatState> = {}) {
  const result = createChatSessionStore()
  sessions.push(result)
  result.store.setState({ activeThreadId: 'a', ...patch })
  return result.store
}
function tree(store: ReturnType<typeof session>, id = 'a') {
  return createElement(ChatStoreContext.Provider, { value: store }, createElement(Probe, { id }))
}
const resolved = (slug: string) => ({ ok: true as const, slug, src: `blob:${slug}`, revoke: vi.fn() })

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(10000)
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  const storage = new Map<string, string>()
  Object.defineProperty(window, 'localStorage', { configurable: true, value: {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => storage.set(key, value)
  } })
  vi.mocked(resolvePetSpritesheetSrc).mockReset().mockImplementation(async slug => resolved(slug || 'boba'))
  root = createRoot(document.createElement('div'))
})
afterEach(async () => {
  await act(async () => root.unmount())
  sessions.splice(0).forEach(session => session.dispose())
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

it('finishes a deferred state change without another stream event', async () => {
  const store = session({ busy: true, currentTurnId: 'turn-a' })
  await act(async () => root.render(tree(store)))
  expect(snapshots.a.stateId).toBe('running')
  await act(async () => {
    vi.advanceTimersByTime(100)
    emitPetEvent('a', { type: 'tool_started', itemId: 't', summary: 'read file' })
  })
  expect(snapshots.a.stateId).toBe('running')
  await act(async () => vi.advanceTimersByTimeAsync(200))
  expect(snapshots.a.stateId).toBe('review')
})

it('waves after a recovered tool error when the turn completes', async () => {
  const store = session({ busy: true, currentTurnId: 'turn-a', blocks: [
    { kind: 'user', id: 'u', text: 'go', turnId: 'turn-a' },
    { kind: 'tool', id: 't', summary: 'read', status: 'error' }
  ] })
  await act(async () => root.render(tree(store)))
  expect(snapshots.a.stateId).toBe('failed')
  await act(async () => vi.advanceTimersByTimeAsync(500))
  await act(async () => {
    emitPetEvent('a', { type: 'turn_complete' })
    store.setState({ busy: false, currentTurnId: null })
  })
  expect(snapshots.a.stateId).toBe('waving')
  await act(async () => vi.advanceTimersByTimeAsync(700))
  expect(snapshots.a.stateId).toBe('running-right')
})

it('clears the old thread error and ignores its late events after switching', async () => {
  const store = session()
  await act(async () => root.render(tree(store)))
  await act(async () => emitPetEvent('a', { type: 'turn_error' }))
  expect(snapshots.a.stateId).toBe('failed')
  await act(async () => store.setState({ activeThreadId: 'b', blocks: [] }))
  await act(async () => {
    emitPetEvent('a', { type: 'turn_error' })
    await vi.advanceTimersByTimeAsync(5000)
  })
  expect(snapshots.a.stateId).toBe('running-right')
})

it('isolates tool and completion events between panes', async () => {
  const a = session({ busy: true, currentTurnId: 'turn-a' })
  const b = session({ activeThreadId: 'b' })
  await act(async () => root.render(createElement('div', null, tree(a, 'a'), tree(b, 'b'))))
  await act(async () => emitPetEvent('a', { type: 'tool_started', itemId: 't', summary: 'read file' }))
  await act(async () => vi.advanceTimersByTimeAsync(300))
  expect(snapshots.a.stateId).toBe('review')
  expect(snapshots.b.stateId).toBe('running-right')
  await act(async () => emitPetEvent('a', { type: 'turn_complete' }))
  expect(snapshots.b.stateId).toBe('running-right')
})

it('clears tool overrides when stopped without a completion event', async () => {
  const store = session({ busy: true, currentTurnId: 'turn-a' })
  await act(async () => root.render(tree(store)))
  await act(async () => {
    vi.advanceTimersByTime(500)
    emitPetEvent('a', { type: 'tool_started', itemId: 't', summary: 'read file' })
  })
  expect(snapshots.a.stateId).toBe('review')
  await act(async () => store.setState({ busy: false, currentTurnId: null, blocks: [] }))
  await act(async () => vi.advanceTimersByTimeAsync(500))
  expect(snapshots.a.stateId).toBe('running-right')
})

it('keeps the latest selection and revokes stale downloads, including after unmount', async () => {
  await act(async () => root.render(tree(session())))
  const pending: Record<string, (value: ReturnType<typeof resolved>) => void> = {}
  vi.mocked(resolvePetSpritesheetSrc).mockImplementation(slug => new Promise(resolve => { pending[slug!] = resolve }))
  await act(async () => writePetSlug('alpha'))
  await act(async () => writePetSlug('beta'))
  const beta = resolved('beta'), alpha = resolved('alpha')
  await act(async () => pending.beta(beta))
  await act(async () => pending.alpha(alpha))
  expect(readPetSlug()).toBe('beta')
  expect(snapshots.a.spritesheetSrc).toBe('blob:beta')
  expect(alpha.revoke).toHaveBeenCalledOnce()
  await act(async () => writePetSlug('gamma'))
  expect(beta.revoke).toHaveBeenCalledOnce()
  await act(async () => root.render(null))
  const gamma = resolved('gamma')
  await act(async () => pending.gamma(gamma))
  expect(gamma.revoke).toHaveBeenCalledOnce()
  expect(readPetSlug()).toBe('gamma')
})

it('falls back on failed image decoding without overwriting the chosen pet', async () => {
  vi.mocked(resolvePetSpritesheetSrc).mockRejectedValue(new Error('decode failed'))
  writePetSlug('chosen')
  await act(async () => root.render(tree(session())))
  expect(snapshots.a.status).toBe('fallback')
  expect(readPetSlug()).toBe('chosen')
})
