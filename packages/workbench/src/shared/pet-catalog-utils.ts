import type { PetManifestSlim } from './pet-manifest'

export function findPetDisplayName(manifest: PetManifestSlim | null, slug: string): string | null {
  if (!manifest) return null
  return manifest.pets.find((pet) => pet.slug === slug)?.displayName ?? null
}

export function filterManifestPets(
  manifest: PetManifestSlim,
  query: string,
  limit = 40
): PetManifestSlim['pets'] {
  const trimmed = query.trim().toLowerCase()
  const pets = trimmed
    ? manifest.pets.filter((pet) => {
        const haystack = [pet.slug, pet.displayName, pet.kind, pet.submittedBy ?? '']
          .join(' ')
          .toLowerCase()
        return haystack.includes(trimmed)
      })
    : manifest.pets
  return pets.slice(0, limit)
}
