import { describe, expect, it } from 'vitest'
import {
  THREAD_MARQUEE_PIXELS_PER_SECOND,
  threadMarqueeDurationMs
} from './thread-marquee'

describe('threadMarqueeDurationMs', () => {
  it('keeps a constant speed across overflow distances', () => {
    for (const distance of [16, 91, 396, 600]) {
      const durationSeconds = threadMarqueeDurationMs(distance) / 1_000
      expect(distance / durationSeconds).toBeCloseTo(THREAD_MARQUEE_PIXELS_PER_SECOND, 5)
    }
  })
})
