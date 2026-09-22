import { expect, it, vi } from 'vitest'
import { emitPetEvent, subscribePetEvents } from './pet-events'

it('routes events only to the matching task and removes subscriptions', () => {
  const a = vi.fn(), b = vi.fn(), draft = vi.fn()
  const stops = [subscribePetEvents('a', a), subscribePetEvents('b', b), subscribePetEvents(null, draft)]
  try {
    emitPetEvent('a', { type: 'turn_error' })
    emitPetEvent(null, { type: 'user_message' })
    expect(a).toHaveBeenCalledExactlyOnceWith({ type: 'turn_error' })
    expect(b).not.toHaveBeenCalled()
    expect(draft).toHaveBeenCalledExactlyOnceWith({ type: 'user_message' })
    stops[0]()
    emitPetEvent('a', { type: 'turn_complete' })
    expect(a).toHaveBeenCalledOnce()
  } finally {
    stops.forEach(stop => stop())
  }
})
