import type { PetManifestSlim } from './pet-manifest'

export function findPetDisplayName(manifest: PetManifestSlim | null, slug: string): string | null {
  if (!manifest) return null
  return manifest.pets.find((pet) => pet.slug === slug)?.displayName ?? null
}
