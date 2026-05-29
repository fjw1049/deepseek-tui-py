import { describe, expect, it } from 'vitest'

import { isAllowedSpritesheetUrl } from './pet-url-allowlist'

describe('isAllowedSpritesheetUrl', () => {
  it('allows petdex R2 host', () => {
    expect(
      isAllowedSpritesheetUrl(
        'https://pub-94495283df974cfea5e98d6a9e3fa462.r2.dev/curated/boba/spritesheet.webp'
      )
    ).toBe(true)
  })

  it('blocks non-https urls', () => {
    expect(isAllowedSpritesheetUrl('http://pub-example.r2.dev/x.webp')).toBe(false)
  })

  it('blocks unrelated hosts', () => {
    expect(isAllowedSpritesheetUrl('https://evil.example/x.webp')).toBe(false)
  })
})
