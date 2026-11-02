// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { ChatStoreContext, createChatSessionStore } from '../store/chat-store'
import type { ChatState } from '../store/chat-store-types'
import { resolvePetSpritesheetSrc } from '../lib/pet/pet-catalog'
import { emitPetEvent, PET_REVEAL_DECISION_EVENT } from '../lib/pet/pet-events'
import type { PetTurnDigest } from '../lib/pet/pet-turn-digest'
import { readPetSlug, writePetAiLines, writePetChatter, writePetSlug } from '../lib/pet/pet-preferences'
import { usePetController } from './use-pet-controller'

vi.mock('react-i18next', async importOriginal => {
  const actual = await importOriginal<typeof import('react-i18next')>()
  const t = (key: string) => key
  const i18n = { language: 'zh' }
  return { ...actual, useTranslation: () => ({ t, i18n }) }
})
vi.mock('../lib/pet/pet-catalog', () => ({
  resolvePetSpritesheetSrc: vi.fn(),
  fetchPetManifest: vi.fn(async () => ({ ok: false, message: 'offline' })),
  findPetDisplayName: vi.fn(() => null)
}))

const sessions: ReturnType<typeof createChatSessionStore>[] = []
const snapshots: Record<string, ReturnType<typeof usePetController>> = {}
let renders = 0
let root: ReturnType<typeof createRoot>
function Probe({ id }: { id: string }) { snapshots[id] = usePetController(); renders += 1; return null }
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
const digest = (patch: Partial<PetTurnDigest> = {}): PetTurnDigest => ({
  outcome: 'completed', durationMs: 1000, toolErrors: 0, testsFailed: false, diffLines: 0, ...patch
})
const userBlock = { kind: 'user' as const, id: 'u', text: 'go', turnId: 'turn-a' }
const pending = { kind: 'approval' as const, id: 'ap', approvalId: 'x', summary: 'Write src/a.ts', status: 'pending' as const }

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
  renders = 0
  root = createRoot(document.createElement('div'))
})
afterEach(async () => {
  await act(async () => root.unmount())
  sessions.splice(0).forEach(session => session.dispose())
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

it('stands idle instead of pacing, and costs no renders while idle', async () => {
  await act(async () => root.render(tree(session())))
  const start = renders
  const seen = new Set<string>()
  for (let i = 0; i < 60; i += 1) {
    await act(async () => vi.advanceTimersByTimeAsync(1000))
    seen.add(snapshots.a.stateId)
  }
  expect([...seen]).toEqual(['idle'])
  expect(renders - start).toBeLessThan(3)
})

it('keeps working after a recovered tool error instead of crying for the rest of the turn', async () => {
  const store = session({ busy: true, currentTurnId: 'turn-a', blocks: [userBlock] })
  await act(async () => root.render(tree(store)))
  await act(async () => {
    store.setState(s => ({ blocks: [...s.blocks, { kind: 'tool', id: 't', summary: 'grep foo', status: 'error' }] }))
    emitPetEvent('a', { type: 'tool_completed', itemId: 't', status: 'error', summary: 'grep foo' })
  })
  await act(async () => vi.advanceTimersByTimeAsync(38_000))
  expect(snapshots.a.stateId).toBe('running')
})

it('waves for a completed turn and stays calm for a cancelled one', async () => {
  const store = session({ busy: true, currentTurnId: 'turn-a' })
  await act(async () => root.render(tree(store)))
  await act(async () => {
    emitPetEvent('a', { type: 'turn_complete', digest: digest() })
    store.setState({ busy: false, currentTurnId: null })
  })
  expect(snapshots.a.stateId).toBe('waving')
  await act(async () => vi.advanceTimersByTimeAsync(700))
  expect(snapshots.a.stateId).toBe('idle')

  await act(async () => store.setState({ busy: true, currentTurnId: 'turn-b' }))
  await act(async () => {
    emitPetEvent('a', { type: 'turn_complete', digest: digest({ outcome: 'cancelled' }) })
    store.setState({ busy: false, currentTurnId: null })
  })
  expect(snapshots.a.stateId).toBe('idle')
  expect(snapshots.a.bubble).toBeNull()
})

it('plays the whole jump when the model starts thinking right away', async () => {
  const store = session()
  await act(async () => root.render(tree(store)))
  await act(async () => {
    store.setState({ busy: true, currentTurnId: 'turn-a' })
    emitPetEvent('a', { type: 'user_message', text: 'go' })
  })
  await act(async () => { vi.advanceTimersByTime(100); emitPetEvent('a', { type: 'agent_reasoning' }) })
  await act(async () => vi.advanceTimersByTimeAsync(700))
  expect(snapshots.a.stateId).toBe('jumping')
  await act(async () => vi.advanceTimersByTimeAsync(100))
  expect(snapshots.a.stateId).toBe('running')
})

it('does not flip between work poses while tools churn', async () => {
  const store = session({ busy: true, currentTurnId: 'turn-a' })
  await act(async () => root.render(tree(store)))
  let flips = 0
  let last = snapshots.a.stateId
  for (let i = 0; i < 12; i += 1) {
    await act(async () => emitPetEvent('a', { type: 'agent_reasoning' }))
    await act(async () => vi.advanceTimersByTimeAsync(400))
    await act(async () => emitPetEvent('a', { type: 'tool_started', itemId: `t${i}`, summary: 'edit a.ts', toolKind: 'file_change' }))
    await act(async () => vi.advanceTimersByTimeAsync(400))
    if (snapshots.a.stateId !== last) { flips += 1; last = snapshots.a.stateId }
    await act(async () => emitPetEvent('a', { type: 'tool_completed', itemId: `t${i}`, status: 'success', summary: 'x' }))
  }
  expect(flips).toBe(0)
})

it('shows a failed turn once, with a bubble that bypasses the chatter cooldown', async () => {
  const store = session({ busy: true, currentTurnId: 'turn-a' })
  await act(async () => root.render(tree(store)))
  await act(async () => emitPetEvent('a', { type: 'turn_error' }))
  expect(snapshots.a.stateId).toBe('failed')
  expect(snapshots.a.bubble?.text).toBe('petLineStreamError1')
  await act(async () => vi.advanceTimersByTimeAsync(1220))
  await act(async () => {
    emitPetEvent('a', { type: 'turn_complete', digest: digest({ outcome: 'failed' }) })
    store.setState({ busy: false, currentTurnId: null })
  })
  expect(snapshots.a.stateId).toBe('idle')
})

it('waits with a sticky bubble, reveals the request on click and nudges once later', async () => {
  const store = session({ busy: true, currentTurnId: 'turn-a', blocks: [userBlock, pending] })
  const revealed = vi.fn()
  window.addEventListener(PET_REVEAL_DECISION_EVENT, revealed)
  try {
    await act(async () => root.render(tree(store)))
    expect(snapshots.a.stateId).toBe('waiting')
    expect(snapshots.a.bubble).toMatchObject({ text: 'petNeedsApproval', sticky: true, action: { type: 'decision' } })
    await act(async () => snapshots.a.activate())
    expect(revealed).toHaveBeenCalledOnce()
    expect(snapshots.a.hearts).toBe(0)
    await act(async () => vi.advanceTimersByTimeAsync(120_000))
    expect(snapshots.a.bubble).toMatchObject({ text: 'petNeedsApprovalAgain', nudge: true })
    await act(async () => store.setState({ blocks: [userBlock, { ...pending, status: 'allowed' }] }))
    expect(snapshots.a.stateId).toBe('running')
    expect(snapshots.a.bubble).toBeNull()
  } finally {
    window.removeEventListener(PET_REVEAL_DECISION_EVENT, revealed)
  }
})

it('pats with hearts, and stays silent but still happy when chatter is off', async () => {
  await act(async () => root.render(tree(session())))
  await act(async () => snapshots.a.activate())
  expect(snapshots.a.hearts).toBe(1)
  expect(['jumping', 'waving']).toContain(snapshots.a.stateId)
  expect(snapshots.a.bubble?.text).toMatch(/^petLinePetted/)
  await act(async () => vi.advanceTimersByTimeAsync(10_000))
  expect(snapshots.a.bubble).toBeNull()

  await act(async () => writePetChatter(false))
  await act(async () => snapshots.a.activate())
  expect(snapshots.a.hearts).toBe(2)
  expect(snapshots.a.bubble).toBeNull()
})

it('answers when named, and keeps chatter to one bubble per cooldown', async () => {
  const store = session()
  await act(async () => root.render(tree(store)))
  await act(async () => emitPetEvent('a', { type: 'user_message', text: 'boba你看看这个' }))
  expect(snapshots.a.bubble?.text).toMatch(/^petLineNamed/)
  await act(async () => {
    store.setState({ busy: true, currentTurnId: 'turn-a' })
    emitPetEvent('a', { type: 'user_message', text: 'next' })
  })
  expect(snapshots.a.bubble).toBeNull()
  await act(async () => emitPetEvent('a', { type: 'turn_complete', digest: digest({ durationMs: 60_000 }) }))
  expect(snapshots.a.bubble).toBeNull()
  await act(async () => vi.advanceTimersByTimeAsync(30_000))
  await act(async () => emitPetEvent('a', { type: 'turn_complete', digest: digest({ durationMs: 60_000 }) }))
  expect(snapshots.a.bubble?.text).toMatch(/^petLineDone/)
})

it('uses an AI line when enabled and falls back to the built-in line on failure', async () => {
  const petReact = vi.fn()
    .mockResolvedValueOnce({ ok: true, text: '又被你摸到了' })
    .mockResolvedValueOnce({ ok: false, message: 'HTTP 500' })
  Object.defineProperty(window, 'dsGui', { configurable: true, value: { petReact } })
  writePetAiLines(true)
  await act(async () => root.render(tree(session())))
  await act(async () => snapshots.a.activate())
  expect(petReact).toHaveBeenCalledWith(expect.objectContaining({ reason: 'petted', petName: 'Boba' }))
  expect(snapshots.a.bubble?.text).toBe('又被你摸到了')
  await act(async () => vi.advanceTimersByTimeAsync(31_000))
  await act(async () => snapshots.a.activate())
  expect(snapshots.a.bubble?.text).toMatch(/^petLinePetted/)
})

it('discards an AI line after switching threads', async () => {
  let resolveReaction!: (value: { ok: true; text: string }) => void
  const petReact = vi.fn(() => new Promise(resolve => { resolveReaction = resolve }))
  Object.defineProperty(window, 'dsGui', { configurable: true, value: { petReact } })
  writePetAiLines(true)
  const store = session()
  await act(async () => root.render(tree(store)))
  await act(async () => snapshots.a.activate())
  expect(petReact).toHaveBeenCalledOnce()
  await act(async () => store.setState({ activeThreadId: 'b' }))
  await act(async () => resolveReaction({ ok: true, text: 'A 的台词' }))
  expect(snapshots.a.bubble).toBeNull()
})

it('points at another task that is waiting, and forgets it once answered', async () => {
  await act(async () => root.render(tree(session())))
  await act(async () => emitPetEvent('other', { type: 'approval_waiting', itemId: 'ap-1' }))
  expect(snapshots.a.bubble).toMatchObject({ text: 'petOtherTaskWaiting', action: { type: 'thread', threadId: 'other' } })
  await act(async () => emitPetEvent('other', { type: 'approval_resolved', itemId: 'ap-1', status: 'allowed' }))
  expect(snapshots.a.bubble).toBeNull()
})

it('isolates tool and completion events between panes', async () => {
  const a = session({ busy: true, currentTurnId: 'turn-a' })
  const b = session({ activeThreadId: 'b' })
  await act(async () => root.render(createElement('div', null, tree(a, 'a'), tree(b, 'b'))))
  await act(async () => emitPetEvent('a', { type: 'tool_started', itemId: 't', summary: 'read file' }))
  await act(async () => vi.advanceTimersByTimeAsync(1800))
  expect(snapshots.a.stateId).toBe('review')
  expect(snapshots.b.stateId).toBe('idle')
  await act(async () => emitPetEvent('a', { type: 'turn_complete', digest: digest() }))
  expect(snapshots.b.stateId).toBe('idle')
})

it('hides until the chosen sheet is ready and keeps the old one while switching', async () => {
  const pendingSheets: Record<string, (value: ReturnType<typeof resolved>) => void> = {}
  vi.mocked(resolvePetSpritesheetSrc).mockImplementation(slug => new Promise(resolve => { pendingSheets[slug!] = resolve }))
  await act(async () => root.render(tree(session())))
  expect(snapshots.a.status).toBe('hidden')
  const boba = resolved('boba')
  await act(async () => pendingSheets.boba(boba))
  expect(snapshots.a.spritesheetSrc).toBe('blob:boba')
  await act(async () => writePetSlug('beta'))
  expect(snapshots.a.spritesheetSrc).toBe('blob:boba')
  const beta = resolved('beta')
  await act(async () => pendingSheets.beta(beta))
  expect(snapshots.a.spritesheetSrc).toBe('blob:beta')
  await act(async () => vi.advanceTimersByTimeAsync(1000))
  expect(boba.revoke).toHaveBeenCalledOnce()
  expect(beta.revoke).not.toHaveBeenCalled()
  expect(readPetSlug()).toBe('beta')
})

it('falls back on failed image decoding without overwriting the chosen pet', async () => {
  vi.mocked(resolvePetSpritesheetSrc).mockRejectedValue(new Error('decode failed'))
  writePetSlug('chosen')
  await act(async () => root.render(tree(session())))
  expect(snapshots.a.status).toBe('fallback')
  expect(readPetSlug()).toBe('chosen')
})

it('wakes the pet for a pat command and rejects unknown commands', async () => {
  await act(async () => root.render(tree(session())))
  await act(async () => snapshots.a.handlePetSlash('/pet tuck'))
  expect(snapshots.a.status).toBe('hidden')
  await act(async () => snapshots.a.handlePetSlash('/pet pat'))
  expect(snapshots.a.status).toBe('ready')
  expect(snapshots.a.hearts).toBe(1)
  expect(snapshots.a.handlePetSlash('/pet dance')).toBe(false)
})
