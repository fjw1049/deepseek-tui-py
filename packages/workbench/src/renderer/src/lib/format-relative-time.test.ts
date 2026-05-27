import { describe, expect, it } from 'vitest'
import { formatRelativeTimeCompact } from './format-relative-time'

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
