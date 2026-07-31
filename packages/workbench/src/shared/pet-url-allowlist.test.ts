import { describe, expect, it } from 'vitest'

import { isAllowedManifestUrl, isAllowedSpritesheetUrl } from './pet-url-allowlist'

describe('isAllowedSpritesheetUrl', () => {
  it('allows legacy petdex R2 host', () => {
    expect(
      isAllowedSpritesheetUrl(
        'https://pub-94495283df974cfea5e98d6a9e3fa462.r2.dev/curated/boba/spritesheet.webp'
      )
    ).toBe(true)
  })

  it('allows assets.petdex.dev sprites', () => {
    expect(
      isAllowedSpritesheetUrl(
        'https://assets.petdex.dev/pets/lulu-capybara-9f9107636ecc/sprite.webp'
      )
    ).toBe(true)
  })

  it('blocks non-https urls', () => {
    expect(isAllowedSpritesheetUrl('http://pub-example.r2.dev/x.webp')).toBe(false)
    expect(isAllowedSpritesheetUrl('http://assets.petdex.dev/x.webp')).toBe(false)
  })

  it('blocks unrelated hosts', () => {
    expect(isAllowedSpritesheetUrl('https://evil.example/x.webp')).toBe(false)
    expect(isAllowedSpritesheetUrl('https://petdex.dev/x.webp')).toBe(false)
  })
})

describe('isAllowedManifestUrl', () => {
  it('allows current and legacy Petdex manifest hosts', () => {
    expect(isAllowedManifestUrl('https://petdex.dev/api/manifest')).toBe(true)
    expect(isAllowedManifestUrl('https://petdex.crafter.run/api/manifest')).toBe(true)
    expect(
      isAllowedManifestUrl('https://assets.petdex.dev/manifests/petdex-v1.json')
    ).toBe(true)
  })

  it('blocks unrelated hosts', () => {
    expect(isAllowedManifestUrl('https://evil.example/api/manifest')).toBe(false)
  })
})
