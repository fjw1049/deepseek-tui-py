import { describe, expect, it } from 'vitest'
import { createRuntimeReadyCache } from './runtime-ready-cache'

describe('runtimeReadyCache', () => {
  it('returns stale before markReady', () => {
    const cache = createRuntimeReadyCache({ now: () => 1000 })
    expect(cache.isFresh()).toBe(false)
  })

  it('serves hits within the TTL window so ensureRuntime can skip probes', () => {
    let now = 1000
    const cache = createRuntimeReadyCache({ ttlMs: 5000, now: () => now })
    cache.markReady()
    now = 5999
    expect(cache.isFresh()).toBe(true)
    now = 6001
    expect(cache.isFresh()).toBe(false)
  })

  it('invalidate forces the next isFresh to miss', () => {
    let now = 1000
    const cache = createRuntimeReadyCache({ ttlMs: 5000, now: () => now })
    cache.markReady()
    expect(cache.isFresh()).toBe(true)
    cache.invalidate('settings-change')
    expect(cache.isFresh()).toBe(false)
  })

  it('emits trace events with the invalidate reason but only when previously fresh', () => {
    const events: Array<[string, string?]> = []
    const cache = createRuntimeReadyCache({
      now: () => 1000,
      onTrace: (event, reason) => events.push([event, reason])
    })
    cache.invalidate('first-call-noise')
    expect(events).toEqual([])
    cache.markReady()
    cache.isFresh()
    cache.invalidate('runtime-request:401')
    expect(events).toEqual([
      ['hit', undefined],
      ['invalidate', 'runtime-request:401']
    ])
  })
})
