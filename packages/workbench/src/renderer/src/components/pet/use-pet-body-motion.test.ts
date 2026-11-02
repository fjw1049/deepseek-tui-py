import { describe, expect, it } from 'vitest'

import { nextPetRestMs, nextPetStrollLeg, PET_STROLL_SPEED_PX_S } from './use-pet-body-motion'

const rolls = (...values: number[]) => {
  let index = 0
  return () => values[index++ % values.length]!
}

describe('nextPetStrollLeg', () => {
  it('walks a short leg at the stroll speed', () => {
    const leg = nextPetStrollLeg(0, 100, rolls(0.5, 0.1))!
    expect(leg.to).toBeCloseTo(56)
    expect(leg.durationMs).toBeCloseTo((56 / PET_STROLL_SPEED_PX_S) * 1000)
  })

  it('stays inside the dock and turns around at an edge', () => {
    const leg = nextPetStrollLeg(95, 100, rolls(0, 0.1))!
    expect(leg.to).toBeLessThan(95)
    expect(leg.to).toBeGreaterThanOrEqual(-100)
  })

  it('has nowhere to go in a dock too narrow to walk', () => {
    expect(nextPetStrollLeg(0, 6)).toBeNull()
  })
})

describe('nextPetRestMs', () => {
  it('rests longer between walks than before the first one', () => {
    expect(nextPetRestMs(true, () => 1)).toBe(16_000)
    expect(nextPetRestMs(false, () => 0)).toBe(20_000)
  })
})
