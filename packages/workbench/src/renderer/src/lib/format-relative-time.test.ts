import { describe, expect, it } from 'vitest'
import { formatRelativeTimeCompact, formatRelativeTimeLargestUnit } from './format-relative-time'

describe('formatRelativeTimeCompact', () => {
  it('formats seconds', () => {
    const now = Date.now()
    expect(formatRelativeTimeCompact(new Date(now - 11_000).toISOString())).toBe('11s')
  })

  it('formats minutes and seconds', () => {
    const now = Date.now()
    expect(formatRelativeTimeCompact(new Date(now - 90_000).toISOString())).toBe('1m30s')
  })

  it('formats hours minutes seconds', () => {
    const now = Date.now()
    const elapsed = (1 * 3600 + 22 * 60 + 3) * 1000
    expect(formatRelativeTimeCompact(new Date(now - elapsed).toISOString())).toBe('1h22m3s')
  })
})

describe('formatRelativeTimeLargestUnit', () => {
  it('uses only the largest unit', () => {
    const now = Date.now()
    expect(formatRelativeTimeLargestUnit(new Date(now - 374_000).toISOString())).toBe('6m')
    expect(formatRelativeTimeLargestUnit(new Date(now - 90_000).toISOString())).toBe('1m')
    expect(formatRelativeTimeLargestUnit(new Date(now - 5_554_000).toISOString())).toBe('1h')
  })
})
