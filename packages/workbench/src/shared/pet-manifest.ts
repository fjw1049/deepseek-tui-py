export type PetManifestEntry = {
  slug: string
  displayName: string
  kind: string
  submittedBy: string | null
  spritesheetUrl: string
  petJsonUrl: string
  zipUrl: string | null
}

export type PetManifestSlim = {
  generatedAt: string
  total: number
  pets: PetManifestEntry[]
}

export type PetManifestFetchResult =
  | { ok: true; manifest: PetManifestSlim; cached: boolean }
  | { ok: false; message: string }

export type PetSpritesheetResolveResult =
  | { ok: true; slug: string; mime: string; base64: string; cached: boolean }
  | { ok: false; message: string }

export type PetFeaturedCacheResult =
  | { ok: true; pets: PetManifestEntry[]; cachedSlugs: string[] }
  | { ok: false; message: string }

export const DEFAULT_PET_SLUG = 'boba'
export const PETDEX_MANIFEST_URL = 'https://petdex.crafter.run/api/manifest'
