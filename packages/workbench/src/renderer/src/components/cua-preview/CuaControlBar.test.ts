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
const button = (label: string) => [...document.querySelectorAll('button')]
  .find(b => b.textContent === label || b.getAttribute('aria-label') === label)
const click = async (label: string) => act(async () => {
  expect(button(label)).toBeTruthy(); button(label)!.click()
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

it('shows only Stop, whatever the host reports about the task', async () => {
  state = { ...state, owner: 'user', paused: true, waiting: true, awaiting_permission: true,
    transferring: true, human_reason: 'Please sign in to continue.',
    unresolved: { call_id: 'submit', turn_id: 'turn' } }
  await render()
  expect(host.textContent).toBe('')
  expect([...host.querySelectorAll('button')].map(b => b.getAttribute('aria-label'))).toEqual(['cuaControlStop'])
})

it('stops the task only after confirmation', async () => {
  useCuaPreviewStore.setState({ sessions: { thread: { phase: 'live', turnId: 'turn', appId: null, surface: null,
    label: null, still: null, revision: 0 } } })
  await render()
  await click('cuaControlStop')
  expect(request.mock.calls.some(c => c[1] === 'POST')).toBe(false)
  state = { ...state, active: false }
  await click('cuaControlStopConfirm')
  const payload = JSON.parse(request.mock.calls.find(c => c[1] === 'POST')![2])
  expect(payload).toEqual({ owner: 'stopped', revision: 3, turn_id: 'turn' })
  expect(useCuaPreviewStore.getState().sessions.thread).toMatchObject({ phase: 'ended', outcome: 'stopped' })
  useCuaPreviewStore.setState({ sessions: {} })
})

it('keeps Stop usable while polls fail', async () => {
  await render()
  request.mockRejectedValue(new Error('offline'))
  await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
  expect(button('cuaControlStop')!.disabled).toBe(false)
})

it('offers no controls for a running turn that has not used computer control', async () => {
  state = { ...state, used: false, owner: 'idle' }
  await render()
  expect(host.querySelectorAll('button')).toHaveLength(0)
  state = { ...state, used: true, owner: 'assistant' }
  await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
  expect(button('cuaControlStop')).toBeTruthy()
})

it('says nothing until the host has answered', async () => {
  let answer!: (value: unknown) => void
  request.mockImplementation(() => new Promise(resolve => { answer = resolve }))
  await render()
  expect(host.innerHTML).toBe('')
  await act(async () => answer({ ok: true, body: JSON.stringify(state) }))
  expect(button('cuaControlStop')).toBeTruthy()
})

it('offers no controls once the card shows the task as ended', async () => {
  useCuaPreviewStore.setState({ sessions: { thread: { phase: 'live', turnId: 'turn', appId: null, surface: null,
    label: null, still: null, revision: 0 } } })
  await render()
  expect(button('cuaControlStop')).toBeTruthy()
  await act(async () => noteCuaTurnEnded('thread', 'completed'))
  expect(host.innerHTML).toBe('')
  useCuaPreviewStore.setState({ sessions: {} })
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
