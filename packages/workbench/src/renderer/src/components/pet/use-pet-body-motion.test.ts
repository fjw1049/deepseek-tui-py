import { describe, expect, it } from 'vitest'

import { nextPetRestMs, nextPetStrollLeg, PET_STROLL_SPEED_PX_S } from './use-pet-body-motion'

const rolls = (...values: number[]) => {
  let index = 0
  return () => values[index++ % values.length]!
}

describe('nextPetStrollLeg', () => {
  it('wanders left from home at the stroll speed', () => {
    const leg = nextPetStrollLeg(0, 200, rolls(0.5, 0.5))!
    expect(leg.to).toBeCloseTo(-56)
    expect(leg.durationMs).toBeCloseTo((56 / PET_STROLL_SPEED_PX_S) * 1000)
  })

  it('heads back toward home from far left and never passes it', () => {
    const leg = nextPetStrollLeg(-190, 200, rolls(0.5, 0.5))!
    expect(leg.to).toBeGreaterThan(-190)
    expect(leg.to).toBeLessThanOrEqual(0)
  })

  it('stays inside the dock at its left end', () => {
    const leg = nextPetStrollLeg(-195, 200, rolls(0.5, 0.95))!
    expect(leg.to).toBeGreaterThanOrEqual(-200)
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
