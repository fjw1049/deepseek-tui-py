import { describe, expect, it } from 'vitest'

import { sanitizeReasoningPlaceholders } from './reasoning-text'

describe('sanitizeReasoningPlaceholders', () => {
  it('removes reasoning omitted placeholder lines', () => {
    expect(sanitizeReasoningPlaceholders('(reasoning omitted)')).toBe('')
    expect(
      sanitizeReasoningPlaceholders('before\n(reasoning omitted)\nafter\n  (reasoning omitted)  ')
    ).toBe('before\nafter')
  })

  it('strips an inline placeholder that prefixes real text', () => {
    expect(sanitizeReasoningPlaceholders('(reasoning omitted)现在看起来已经完成了')).toBe(
      '现在看起来已经完成了'
    )
  })

  it('keeps normal text intact', () => {
    expect(sanitizeReasoningPlaceholders('real reasoning\nwith details')).toBe(
      'real reasoning\nwith details'
    )
  })
})
