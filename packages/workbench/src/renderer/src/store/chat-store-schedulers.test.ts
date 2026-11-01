import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createChatSchedulers } from './chat-store-schedulers'
import type { ChatState, ChatStoreGet, ChatStoreSet } from './chat-store-types'

const TIMEOUT = 120_000
let recoverActiveTurn: ReturnType<typeof vi.fn>
let get: ChatStoreGet
const set = vi.fn() as unknown as ChatStoreSet
const options = (isWaitingOnHuman?: () => Promise<boolean>) => ({
  timeoutMs: TIMEOUT, maxAttempts: 3, finalizeBusyState: () => ({}), flushLiveBlocks: () => ({}),
  busyTimeoutMessage: () => 'timeout', isWaitingOnHuman
})

beforeEach(() => {
  vi.useFakeTimers()
  recoverActiveTurn = vi.fn(async () => true)
  const state = { busy: true, activeThreadId: 'a', recoverActiveTurn } as unknown as ChatState
  get = () => state
})
afterEach(() => { vi.useRealTimers() })

it('does not treat a person holding the task as a broken stream', async () => {
  const { armBusyWatchdog, clearBusyWatchdog } = createChatSchedulers()
  const waiting = vi.fn(async () => true)
  armBusyWatchdog(set, get, options(waiting))
  await vi.advanceTimersByTimeAsync(TIMEOUT * 3)
  expect(waiting).toHaveBeenCalledTimes(3)
  expect(recoverActiveTurn).not.toHaveBeenCalled()
  waiting.mockResolvedValue(false)
  await vi.advanceTimersByTimeAsync(TIMEOUT)
  expect(recoverActiveTurn).toHaveBeenCalledOnce()
  clearBusyWatchdog()
})

it('recovers as before when the check fails or nobody is holding it', async () => {
  const { armBusyWatchdog, clearBusyWatchdog } = createChatSchedulers()
  armBusyWatchdog(set, get, options(async () => { throw new Error('offline') }))
  await vi.advanceTimersByTimeAsync(TIMEOUT)
  expect(recoverActiveTurn).toHaveBeenCalledOnce()
  armBusyWatchdog(set, get, options())
  await vi.advanceTimersByTimeAsync(TIMEOUT)
  expect(recoverActiveTurn).toHaveBeenCalledTimes(2)
  clearBusyWatchdog()
})

it('drops a check that stream activity overtook', async () => {
  const { armBusyWatchdog, clearBusyWatchdog } = createChatSchedulers()
  let answer!: (waiting: boolean) => void
  armBusyWatchdog(set, get, options(() => new Promise((resolve) => { answer = resolve })))
  await vi.advanceTimersByTimeAsync(TIMEOUT)
  clearBusyWatchdog()
  answer(false)
  await vi.advanceTimersByTimeAsync(0)
  expect(recoverActiveTurn).not.toHaveBeenCalled()
})
