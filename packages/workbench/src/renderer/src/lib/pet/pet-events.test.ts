import { expect, it, vi } from 'vitest'
import { emitPetEvent, subscribeAllPetEvents, subscribePetEvents } from './pet-events'

const digest = { outcome: 'completed', durationMs: 0, toolErrors: 0, testsFailed: false, diffLines: 0 } as const

it('routes events only to the matching task and removes subscriptions', () => {
  const a = vi.fn(), b = vi.fn(), draft = vi.fn(), all = vi.fn()
  const stops = [
    subscribePetEvents('a', a), subscribePetEvents('b', b), subscribePetEvents(null, draft),
    subscribeAllPetEvents(all)
  ]
  try {
    emitPetEvent('a', { type: 'turn_error' })
    emitPetEvent(null, { type: 'user_message' })
    expect(a).toHaveBeenCalledExactlyOnceWith({ type: 'turn_error' })
    expect(b).not.toHaveBeenCalled()
    expect(draft).toHaveBeenCalledExactlyOnceWith({ type: 'user_message' })
    expect(all).toHaveBeenCalledWith('a', { type: 'turn_error' })
    stops[0]()
    emitPetEvent('a', { type: 'turn_complete', digest })
    expect(a).toHaveBeenCalledOnce()
  } finally {
    stops.forEach(stop => stop())
  }
})
