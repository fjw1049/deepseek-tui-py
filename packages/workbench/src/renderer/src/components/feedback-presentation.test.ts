// @vitest-environment happy-dom
import { act, createElement, useState } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { ChatBlock } from '../agent/types'
import { FeedbackNotice } from './FeedbackNotice'
import { PendingDecisionPanel } from './chat/PendingDecisionPanel'
import { ConnectionStatusBar } from './ConnectionStatusBar'
import { useNoticeAutoDismiss, type Notice } from './extensions/marketplace-shared'

const state = vi.hoisted(() => ({
  refreshPendingUserInputs: vi.fn(async () => {}), probeRuntime: vi.fn(async () => {}),
  runtimeConnection: 'ready', activeThreadId: null, activeThreadWarmup: {}, startupPhase: null
}))
vi.mock('../store/chat-store', () => ({ useChatStore: (select: (s: typeof state) => unknown) => select(state) }))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
vi.mock('./chat/ApprovalBubble', () => ({ ApprovalBubble: ({ block }: { block: ChatBlock }) => createElement('p', null, block.id) }))
vi.mock('./chat/ElevationBubble', () => ({ ElevationBubble: () => null }))
vi.mock('./chat/UserInputBubble', () => ({ UserInputBubble: () => {
  const [draft, setDraft] = useState('')
  return createElement('input', { value: draft, onChange: (e) => setDraft(e.target.value) })
} }))
let host: HTMLDivElement
let root: Root
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  vi.clearAllMocks()
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
})
afterEach(() => { act(() => root.unmount()); host.remove(); vi.useRealTimers(); vi.restoreAllMocks() })

it('keeps actionable information and errors while transient success expires', async () => {
  vi.useFakeTimers()
  const dismiss = vi.fn()
  function Timer({ notice }: { notice: Notice }) { useNoticeAutoDismiss(notice, dismiss); return null }
  for (const notice of [{ tone: 'info', message: 'Restart required', persistent: true }, { tone: 'error', message: 'Failed' }] satisfies Notice[]) {
    await act(async () => root.render(createElement(Timer, { notice })))
    act(() => vi.advanceTimersByTime(10000))
    expect(dismiss).not.toHaveBeenCalled()
  }
  await act(async () => root.render(createElement(Timer, { notice: { tone: 'success', message: 'Saved' } })))
  act(() => vi.advanceTimersByTime(3000))
  expect(dismiss).toHaveBeenCalledWith(null)
})

it('gives transient feedback reading time after returning to the window', async () => {
  vi.useFakeTimers()
  const visibility = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden')
  const dismiss = vi.fn()
  function Timer() { useNoticeAutoDismiss({ tone: 'success', message: 'Saved' }, dismiss); return null }
  await act(async () => root.render(createElement(Timer)))
  act(() => vi.advanceTimersByTime(10000))
  expect(dismiss).not.toHaveBeenCalled()
  visibility.mockReturnValue('visible')
  act(() => document.dispatchEvent(new Event('visibilitychange')))
  act(() => vi.advanceTimersByTime(2999))
  expect(dismiss).not.toHaveBeenCalled()
  act(() => vi.advanceTimersByTime(1))
  expect(dismiss).toHaveBeenCalledWith(null)
})

it('keeps long diagnostic text collapsed and makes dismissal accessible', async () => {
  const dismiss = vi.fn(); const message = 'failure '.repeat(100)
  await act(async () => root.render(createElement(FeedbackNotice, { tone: 'error', message, onDismiss: dismiss })))
  expect(host.querySelector('[role="alert"]')).not.toBeNull()
  expect(host.querySelector('details')?.open).toBe(false)
  expect(host.querySelector('details p')?.textContent).toBe(message)
  act(() => host.querySelector<HTMLButtonElement>('[aria-label="dismissNotice"]')!.click())
  expect(dismiss).toHaveBeenCalledOnce()
})

const pending: ChatBlock[] = [
  { kind: 'user_input', id: 'question', requestId: 'q', questions: [], status: 'pending' },
  { kind: 'approval', id: 'command', approvalId: 'a', summary: 'Run tests', status: 'pending' }
]
it('shows one request and retains its draft through switching and collapsing', async () => {
  await act(async () => root.render(createElement(PendingDecisionPanel, { blocks: pending })))
  const input = host.querySelector('input')!
  act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, 'keep my answer')
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
  const select = host.querySelector('select')!
  act(() => { select.value = 'command'; select.dispatchEvent(new Event('change', { bubbles: true })) })
  expect(input.closest('[hidden]')).not.toBeNull()
  act(() => { select.value = 'question'; select.dispatchEvent(new Event('change', { bubbles: true })) })
  expect(host.querySelector('input')).toBe(input)
  expect(input.value).toBe('keep my answer')
  act(() => host.querySelector<HTMLButtonElement>('[aria-expanded]')!.click())
  expect(input.closest('[hidden]')).not.toBeNull()
  act(() => host.querySelector<HTMLButtonElement>('[aria-expanded]')!.click())
  expect(input.value).toBe('keep my answer')
  await act(async () => root.render(createElement(PendingDecisionPanel, { blocks: pending.slice(1) })))
  expect(host.textContent).toContain('command')
  expect(host.querySelector('select')).toBeNull()
})

it('prioritizes an uncertain submission and checks status without resubmitting', async () => {
  const blocks: ChatBlock[] = [...pending, { kind: 'approval', id: 'failed', approvalId: 'f', summary: '', status: 'error', submissionFailed: true, errorMessage: 'timeout' }]
  let finish!: () => void
  state.refreshPendingUserInputs.mockImplementationOnce(() => new Promise<void>((resolve) => { finish = resolve }))
  await act(async () => root.render(createElement(PendingDecisionPanel, { blocks })))
  expect(host.querySelector('select')?.value).toBe('failed')
  const check = [...host.querySelectorAll('button')].find(b => b.textContent === 'decisionCheckStatus')!
  act(() => check.click())
  expect(check.disabled).toBe(true)
  act(() => check.click())
  expect(state.refreshPendingUserInputs).toHaveBeenCalledOnce()
  await act(async () => finish())
  expect(check.disabled).toBe(false)
})

it('uses neutral checking and a readable offline retry, then clears on recovery', async () => {
  state.runtimeConnection = 'checking'
  await act(async () => root.render(createElement(ConnectionStatusBar, { compact: true })))
  expect(host.innerHTML).not.toContain('animate-pulse')
  expect(host.innerHTML).not.toContain('text-amber')
  state.runtimeConnection = 'offline'
  await act(async () => root.render(createElement(ConnectionStatusBar, { compact: true })))
  expect(host.innerHTML).toContain('text-amber')
  await act(async () => host.querySelector('button')!.click())
  expect(state.probeRuntime).toHaveBeenCalledWith('user')
  state.runtimeConnection = 'ready'
  await act(async () => root.render(createElement(ConnectionStatusBar)))
  expect(host.innerHTML).toBe('')
})
