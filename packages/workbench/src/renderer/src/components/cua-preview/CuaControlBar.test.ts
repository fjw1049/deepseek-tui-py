// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { CuaControlBar, type CuaControlState } from './CuaControlBar'
import { noteCuaTurnEnded, refreshCuaPreview, useCuaPreviewStore } from '../../store/cua-preview-store'

const translate = (key: string) => key
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: translate }) }))
globalThis.IS_REACT_ACT_ENVIRONMENT = true
let root: ReturnType<typeof createRoot>
let host: HTMLDivElement
let state: CuaControlState
let request: ReturnType<typeof vi.fn>
const render = () => act(async () => root.render(createElement(CuaControlBar, { threadId: 'thread' })))
const click = async (text: string) => act(async () => {
  const button = [...host.querySelectorAll('button')].find(b => b.textContent === text)
  expect(button).toBeTruthy(); button!.click()
})
beforeEach(() => {
  vi.useFakeTimers()
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
  state = { active: true, available: true, turn_id: 'turn', revision: 3, owner: 'assistant',
    waiting: false, paused: false, human_reason: null, unresolved: null, holder: null }
  request = vi.fn(async () => ({ ok: true, body: JSON.stringify(state) }))
  Object.defineProperty(window, 'dsGui', { configurable: true, value: { runtimeRequest: request } })
})
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.useRealTimers() })

it('does not claim human control before the host acknowledges transfer', async () => {
  await render()
  let finish!: (value: unknown) => void
  request.mockImplementation(async (_path, method) => method === 'POST'
    ? new Promise(resolve => { finish = resolve }) : { ok: true, body: JSON.stringify(state) })
  await click('cuaControlTakeover')
  expect(host.textContent).toContain('cuaControlTransferring')
  expect(host.textContent).not.toContain('cuaControlHuman')
  state = { ...state, owner: 'user', paused: true, revision: 4 }
  await act(async () => finish({ ok: true, body: JSON.stringify(state) }))
  expect(host.textContent).toContain('cuaControlHuman')
  const payload = JSON.parse(request.mock.calls.find(c => c[1] === 'POST')![2])
  expect(payload).toEqual({ owner: 'user', revision: 3, turn_id: 'turn' })
})

it('requires taking control before confirming an unknown operation', async () => {
  state.unresolved = { call_id: 'submit', turn_id: 'turn' }
  await render()
  expect(host.textContent).toContain('cuaControlUnknownHint')
  expect(host.textContent).not.toContain('cuaControlReviewed')
  state = { ...state, owner: 'user', paused: true, revision: 4 }
  await click('cuaControlTakeover')
  await click('cuaControlReviewed')
  const payload = JSON.parse(request.mock.calls.filter(c => c[1] === 'POST').at(-1)![2])
  expect(payload).toMatchObject({ owner: 'assistant', reviewed_call_id: 'submit', revision: 4 })
})

it('retains stop when polling loses connection and disables stale takeover', async () => {
  await render()
  request.mockRejectedValue(new Error('offline'))
  await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
  // One lost request is not a lost connection.
  expect(host.textContent).not.toContain('cuaControlDisconnected')
  expect([...host.querySelectorAll('button')].find(b => b.textContent === 'cuaControlTakeover')!.disabled).toBe(false)
  await act(async () => { await vi.advanceTimersByTimeAsync(2000) })
  const buttons = [...host.querySelectorAll('button')]
  expect(buttons.find(b => b.textContent === 'cuaControlTakeover')!.disabled).toBe(true)
  expect(buttons.find(b => b.textContent === 'cuaControlStop')!.disabled).toBe(false)
})

it('shows permission waiting instead of claiming the assistant is operating', async () => {
  state.awaiting_permission = true
  await render()
  expect(host.querySelector('[role="status"]')!.textContent).toBe('cuaControlPermission')
})

it('keeps lengthy manual instructions collapsed without hiding continue', async () => {
  state.owner = 'user'
  state.human_reason = 'Inspect the document before continuing. '.repeat(30)
  await render()
  expect(host.querySelector('details')!.open).toBe(false)
  expect(host.querySelector('summary')!.textContent).toBe('cuaControlHelpDetails')
  expect([...host.querySelectorAll('button')].some(b => b.textContent === 'cuaControlContinue')).toBe(true)
})


it('shows required human instructions directly in the compact entry', async () => {
  state.owner = 'user'
  state.human_reason = 'Please sign in to continue.'
  await act(async () => root.render(createElement(CuaControlBar, { threadId: 'thread', compact: true })))
  expect(host.querySelector('details')).toBeNull()
  expect(host.textContent).toContain(state.human_reason)
  expect(host.textContent).toContain('cuaControlContinue')
})

it('offers no desktop controls for a running turn that has not used computer control', async () => {
  state = { ...state, used: false, owner: 'idle' }
  await render()
  expect(host.querySelectorAll('button')).toHaveLength(0)
  state = { ...state, used: true, owner: 'assistant' }
  await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
  expect([...host.querySelectorAll('button')].map(b => b.textContent)).toContain('cuaControlTakeover')
})

it('publishes who holds the task so every surface can show it', async () => {
  useCuaPreviewStore.setState({ sessions: { thread: { phase: 'live', turnId: 'turn', appId: null, surface: null,
    label: null, still: null, revision: 0 } } })
  const control = () => useCuaPreviewStore.getState().sessions.thread?.control
  await render()
  expect(control()).toBeUndefined()
  state = { ...state, owner: 'user', paused: true }
  await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
  expect(control()).toBe('user')
  state = { ...state, owner: 'idle', paused: true }
  await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
  expect(control()).toBe('paused')
  state = { ...state, active: false, paused: false }
  await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
  expect(control()).toBeUndefined()
  useCuaPreviewStore.setState({ sessions: {} })
})

it('shows why the host refused a transfer', async () => {
  await render()
  request.mockImplementation(async (_path, method) => method === 'POST'
    ? { ok: false, body: JSON.stringify({ detail: { message: 'The desktop is in use' } }) }
    : { ok: true, body: JSON.stringify(state) })
  await click('cuaControlTakeover')
  expect(host.querySelector('[role=alert]')?.textContent).toBe('The desktop is in use')
})

it('falls back to a generic message when the host gave no reason', async () => {
  await render()
  request.mockImplementation(async (_path, method) => method === 'POST'
    ? { ok: false, body: 'bad gateway' } : { ok: true, body: JSON.stringify(state) })
  await click('cuaControlTakeover')
  expect(host.querySelector('[role=alert]')?.textContent).toBe('cuaControlRetry')
})

it('says nothing until the host has answered', async () => {
  let answer!: (value: unknown) => void
  request.mockImplementation(() => new Promise(resolve => { answer = resolve }))
  await render()
  expect(host.textContent).toBe('')
  await act(async () => answer({ ok: true, body: JSON.stringify(state) }))
  expect(host.textContent).toContain('cuaControlTakeover')
})

it('re-reads control the moment a call or handoff is noted, without doubling the poll', async () => {
  useCuaPreviewStore.setState({ sessions: { thread: { phase: 'live', turnId: 'turn', appId: null, surface: null,
    label: null, still: null, revision: 0 } } })
  await render()
  const reads = () => request.mock.calls.filter(call => call[1] === 'GET').length
  expect(reads()).toBe(1)
  await act(async () => { refreshCuaPreview('thread'); await vi.advanceTimersByTimeAsync(0) })
  expect(reads()).toBe(2)
  await act(async () => { await vi.advanceTimersByTimeAsync(999) })
  expect(reads()).toBe(2)
  await act(async () => { await vi.advanceTimersByTimeAsync(1) })
  expect(reads()).toBe(3)
  useCuaPreviewStore.setState({ sessions: {} })
})

it('ends a live card whose completion event was lost', async () => {
  const session = { phase: 'live', turnId: 'turn', appId: null, surface: null, label: null, still: null, revision: 0 } as const
  useCuaPreviewStore.setState({ sessions: { thread: session } })
  state = { ...state, active: false, turn_id: null }
  await render()
  expect(useCuaPreviewStore.getState().sessions.thread?.phase).toBe('live')
  await act(async () => { await vi.advanceTimersByTimeAsync(3000) })
  expect(useCuaPreviewStore.getState().sessions.thread).toMatchObject({ phase: 'ended', outcome: 'ended' })
  useCuaPreviewStore.setState({ sessions: {} })
})

it('slows down between tasks', async () => {
  state = { ...state, active: false, turn_id: null }
  await render()
  const reads = () => request.mock.calls.filter(call => call[1] === 'GET').length
  await act(async () => { await vi.advanceTimersByTimeAsync(2999) })
  expect(reads()).toBe(1)
  await act(async () => { await vi.advanceTimersByTimeAsync(1) })
  expect(reads()).toBe(2)
})

it('lets Stop overtake a transfer that is still running, without reporting the transfer failing', async () => {
  await render()
  const finish: Array<(value: unknown) => void> = []
  const posted: string[] = []
  request.mockImplementation(async (_path, method, body) => {
    if (method !== 'POST') return { ok: true, body: JSON.stringify(state) }
    posted.push(JSON.parse(body).owner)
    return new Promise(resolve => { finish.push(resolve) })
  })
  await click('cuaControlTakeover')
  expect(host.textContent).toContain('cuaControlTransferring')
  await click('cuaControlStop')
  expect(posted).toEqual(['user', 'stopped'])
  state = { ...state, active: false }
  await act(async () => {
    finish[0]({ ok: false, body: JSON.stringify({ detail: { message: 'The original task ended during transfer' } }) })
    finish[1]({ ok: true, body: JSON.stringify(state) })
  })
  expect(host.querySelector('[role=alert]')).toBeNull()
})

it('clears a refusal instead of leaving it on the card for the rest of the task', async () => {
  await render()
  request.mockImplementation(async (_path, method) => method === 'POST'
    ? { ok: false, body: JSON.stringify({ detail: { message: 'busy' } }) } : { ok: true, body: JSON.stringify(state) })
  await click('cuaControlTakeover')
  expect(host.querySelector('[role=alert]')).not.toBeNull()
  await act(async () => { await vi.advanceTimersByTimeAsync(6000) })
  expect(host.querySelector('[role=alert]')).toBeNull()
})

it('offers no controls once the card shows the task as ended', async () => {
  useCuaPreviewStore.setState({ sessions: { thread: { phase: 'live', turnId: 'turn', appId: null, surface: null,
    label: null, still: null, revision: 0 } } })
  await render()
  expect(host.textContent).toContain('cuaControlTakeover')
  await act(async () => noteCuaTurnEnded('thread', 'completed'))
  expect(host.textContent).toBe('')
  useCuaPreviewStore.setState({ sessions: {} })
})
