import type {
  PetManifestFetchResult,
  PetSpritesheetResolveResult
} from '@shared/pet-manifest'
import { DEFAULT_PET_SLUG } from '@shared/pet-manifest'
import { filterManifestPets, findPetDisplayName } from '@shared/pet-catalog-utils'

export { filterManifestPets, findPetDisplayName }

function base64ToObjectUrl(base64: string, mime: string): string {
  const binary = atob(base64)
  const bytes = new Uint8Array(binary.length)
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index)
  }
  return URL.createObjectURL(new Blob([bytes], { type: mime }))
}

export async function fetchPetManifest(force = false): Promise<PetManifestFetchResult> {
  if (typeof window.dsGui?.fetchPetManifest !== 'function') {
    return { ok: false, message: 'Pet manifest API is unavailable in this shell.' }
  }
  return window.dsGui.fetchPetManifest(force)
}

export async function resolvePetSpritesheetSrc(
  slugInput?: string
): Promise<{
  ok: true
  slug: string
  src: string
  revoke: () => void
}> {
  const slug = slugInput?.trim() || DEFAULT_PET_SLUG
  if (typeof window.dsGui?.resolvePetSpritesheet !== 'function') {
    throw new Error('Pet spritesheet API is unavailable in this shell.')
  }
  const result: PetSpritesheetResolveResult = await window.dsGui.resolvePetSpritesheet(slug)
  if (!result.ok) {
    throw new Error(result.message)
  }
  const src = base64ToObjectUrl(result.base64, result.mime)
  return {
    ok: true,
    slug: result.slug,
    src,
    revoke: () => URL.revokeObjectURL(src)
  }
}
