import { describe, expect, it } from 'vitest'

import type { PetManifestSlim } from './pet-manifest'
import { filterManifestPets } from './pet-catalog-utils'

const manifest: PetManifestSlim = {
  generatedAt: '2026-01-01T00:00:00.000Z',
  total: 3,
  pets: [
    {
      slug: 'boba',
      displayName: 'Boba',
      kind: 'creature',
      submittedBy: 'railly',
      spritesheetUrl: 'https://pub-94495283df974cfea5e98d6a9e3fa462.r2.dev/curated/boba/spritesheet.webp',
      petJsonUrl: 'https://example.com/pet.json',
      zipUrl: null
    },
    {
      slug: 'scoop',
      displayName: 'Scoop',
      kind: 'creature',
      submittedBy: 'demo',
      spritesheetUrl: 'https://pub-94495283df974cfea5e98d6a9e3fa462.r2.dev/curated/scoop/spritesheet.webp',
      petJsonUrl: 'https://example.com/pet.json',
      zipUrl: null
    },
    {
      slug: 'pikachu-fan',
      displayName: 'Pikachu',
      kind: 'character',
      submittedBy: 'ash',
      spritesheetUrl: 'https://pub-94495283df974cfea5e98d6a9e3fa462.r2.dev/pets/pikachu/sprite.webp',
      petJsonUrl: 'https://example.com/pet.json',
      zipUrl: null
    }
  ]
}

describe('filterManifestPets', () => {
  it('returns the first slice when query is empty', () => {
    expect(filterManifestPets(manifest, '', 2)).toHaveLength(2)
  })

  it('filters by slug and display name', () => {
    expect(filterManifestPets(manifest, 'pika', 10).map((pet) => pet.slug)).toEqual([
      'pikachu-fan'
    ])
    expect(filterManifestPets(manifest, 'scoop', 10).map((pet) => pet.slug)).toEqual(['scoop'])
  })
})
