import { describe, expect, it } from 'vitest'

import {
  clampEffortIndex,
  effortTierKey,
  effortValueAttribute
} from './clamp-effort-index'

describe('clampEffortIndex', () => {
  it('keeps numeric Ultra index 4', () => {
    expect(clampEffortIndex(4)).toBe(4)
    expect(effortValueAttribute(4)).toBe('4')
    expect(effortTierKey(4)).toBe('Ultra')
  })

  it('keeps React 19 string property assignment for Ultra', () => {
    // React syncs <reasoning-effort-selector value={String(index)} /> via
    // the custom-element property setter as a string, not a number.
    expect(clampEffortIndex('4')).toBe(4)
    expect(effortValueAttribute('4')).toBe('4')
    expect(effortTierKey('4')).toBe('Ultra')
  })

  it('does not fall back string Ultra to High', () => {
    // Regression: Number.isFinite("4") === false previously returned 2 (High).
    expect(effortTierKey('4')).not.toBe('High')
    expect(effortValueAttribute('4')).not.toBe('2')
  })

  it('clamps out-of-range and invalid values', () => {
    expect(clampEffortIndex(-1)).toBe(0)
    expect(clampEffortIndex(9)).toBe(4)
    expect(clampEffortIndex('nope')).toBe(2)
    expect(clampEffortIndex(undefined)).toBe(2)
    expect(effortTierKey('2')).toBe('High')
  })
})
