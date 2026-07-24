import { describe, expect, it } from 'vitest'
import {
  dayPartFor,
  formatDayPartRange,
  greetingFlairKeyForDayPart,
  greetingKeyForDayPart,
  type DayPart
} from './daypart'

describe('dayPartFor', () => {
  it('maps each Chinese day-part window', () => {
    const samples: Array<[number, DayPart]> = [
      [5, 'morning'],
      [10, 'morning'],
      [11, 'noon'],
      [13, 'noon'],
      [14, 'afternoon'],
      [16, 'afternoon'],
      [17, 'dusk'],
      [18, 'dusk'],
      [19, 'evening'],
      [21, 'evening'],
      [22, 'night'],
      [23, 'night'],
      [0, 'night'],
      [4, 'night']
    ]
    for (const [hour, part] of samples) {
      expect(dayPartFor(hour), `hour ${hour}`).toBe(part)
    }
  })

  it('normalizes out-of-range hours', () => {
    expect(dayPartFor(25)).toBe('night') // 25 → 1
    expect(dayPartFor(-1)).toBe('night') // -1 → 23
  })
})

describe('greeting keys', () => {
  it('builds i18n keys from day-part id', () => {
    expect(greetingKeyForDayPart('noon')).toBe('greetingNoon')
    expect(greetingFlairKeyForDayPart('dusk')).toBe('greetingFlairDusk')
  })
})

describe('formatDayPartRange', () => {
  it('formats inclusive/exclusive windows', () => {
    expect(formatDayPartRange('morning')).toBe('05:00 – 11:00')
    expect(formatDayPartRange('night')).toBe('22:00 – 05:00')
  })
})
