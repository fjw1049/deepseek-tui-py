import { describe, expect, it } from 'vitest'
import { LARGE_PASTE_MIN_CHARS, isLargePaste } from './composer-paste-file'

describe('isLargePaste', () => {
  it('keeps short snippets inline', () => {
    expect(isLargePaste('fix this')).toBe(false)
    expect(isLargePaste('line1\nline2\nline3')).toBe(false)
    expect(isLargePaste('   ')).toBe(false)
  })

  it('treats many lines or a long blob as a file paste', () => {
    expect(isLargePaste(Array.from({ length: 8 }, (_, i) => `line ${i}`).join('\n'))).toBe(
      true
    )
    expect(isLargePaste('x'.repeat(LARGE_PASTE_MIN_CHARS))).toBe(true)
  })
})
