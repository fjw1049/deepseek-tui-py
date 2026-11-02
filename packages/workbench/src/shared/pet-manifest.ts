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

export type PetReactionRequest = {
  reason: 'turn_done' | 'turn_recovered' | 'tests_failed' | 'large_diff' | 'petted' | 'named'
  petName: string
  locale: string
  /** The pet's own recent lines, so it does not repeat itself. */
  recent: string[]
  /** A short excerpt of the latest exchange. */
  context: string
}

export type PetReactionResult =
  | { ok: true; text: string }
  | { ok: false; message: string }

export const DEFAULT_PET_SLUG = 'boba'
/** Canonical Petdex manifest (crafter.run redirects here). */
export const PETDEX_MANIFEST_URL = 'https://petdex.dev/api/manifest'
