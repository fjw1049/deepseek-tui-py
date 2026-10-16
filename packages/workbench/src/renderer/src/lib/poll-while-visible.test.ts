// @vitest-environment happy-dom
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { pollWhileVisible } from './poll-while-visible'

let visibility: DocumentVisibilityState = 'visible'
beforeEach(() => {
  vi.useFakeTimers()
  visibility = 'visible'
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => visibility })
})
afterEach(() => vi.useRealTimers())

function setVisibility(next: DocumentVisibilityState): void {
  visibility = next
  document.dispatchEvent(new Event('visibilitychange'))
}

it('skips ticks while hidden and catches up once visible again', () => {
  const tick = vi.fn()
  const stop = pollWhileVisible(tick, 1000)
  vi.advanceTimersByTime(2000)
  expect(tick).toHaveBeenCalledTimes(2)
  setVisibility('hidden')
  vi.advanceTimersByTime(5000)
  expect(tick).toHaveBeenCalledTimes(2)
  setVisibility('visible')
  expect(tick).toHaveBeenCalledTimes(3)
  stop()
  vi.advanceTimersByTime(5000)
  setVisibility('hidden')
  setVisibility('visible')
  expect(tick).toHaveBeenCalledTimes(3)
})
