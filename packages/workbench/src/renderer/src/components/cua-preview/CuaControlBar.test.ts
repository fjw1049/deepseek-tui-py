// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { CuaControlBar, type CuaControlState } from './CuaControlBar'

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
