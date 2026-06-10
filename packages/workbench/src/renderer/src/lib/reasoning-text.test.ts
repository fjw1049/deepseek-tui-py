import { describe, expect, it } from 'vitest'

import { sanitizeReasoningPlaceholders } from './reasoning-text'

describe('sanitizeReasoningPlaceholders', () => {
  it('removes reasoning omitted placeholder lines', () => {
    expect(sanitizeReasoningPlaceholders('(reasoning omitted)')).toBe('')
    expect(
      sanitizeReasoningPlaceholders('before\n(reasoning omitted)\nafter\n  (reasoning omitted)  ')
    ).toBe('before\nafter')
  })

  it('keeps normal text intact', () => {
    expect(sanitizeReasoningPlaceholders('real reasoning\nwith details')).toBe(
      'real reasoning\nwith details'
    )
  })
})
