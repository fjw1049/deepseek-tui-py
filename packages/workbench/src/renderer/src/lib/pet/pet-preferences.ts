const ENABLED_KEY = 'deepseekgui.pet.enabled'
const SLUG_KEY = 'deepseekgui.pet.slug'
const FAVORITES_KEY = 'deepseekgui.pet.favoriteSlugs'
const MAX_FAVORITE_PETS = 15

type PetPreferencesListener = () => void

const listeners = new Set<PetPreferencesListener>()

function notifyPetPreferences(): void {
  for (const listener of listeners) {
    listener()
  }
}

export function subscribePetPreferences(listener: PetPreferencesListener): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function readPetEnabled(): boolean {
  try {
    const raw = window.localStorage.getItem(ENABLED_KEY)
    if (raw === '0') return false
  } catch {
    /* ignore */
  }
  return true
}

export function writePetEnabled(enabled: boolean): void {
  try {
    window.localStorage.setItem(ENABLED_KEY, enabled ? '1' : '0')
    notifyPetPreferences()
  } catch {
    /* ignore */
  }
}

export function readPetSlug(): string {
  try {
    const raw = window.localStorage.getItem(SLUG_KEY)?.trim()
    if (raw) return raw.slice(0, 80)
  } catch {
    /* ignore */
  }
  return 'boba'
}

export function writePetSlug(slug: string): void {
  try {
    window.localStorage.setItem(SLUG_KEY, slug.trim().slice(0, 80))
    notifyPetPreferences()
  } catch {
    /* ignore */
  }
}

function normalizeFavoriteSlugs(slugs: string[]): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const slug of slugs) {
    const clean = slug.trim().slice(0, 80)
    if (!clean || seen.has(clean)) continue
    seen.add(clean)
    out.push(clean)
    if (out.length >= MAX_FAVORITE_PETS) break
  }
  return out
}

export function readPetFavoriteSlugs(): string[] {
  try {
    const raw = window.localStorage.getItem(FAVORITES_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw) as unknown
    if (!Array.isArray(parsed)) return []
    return normalizeFavoriteSlugs(parsed.filter((item): item is string => typeof item === 'string'))
  } catch {
    return []
  }
}

export function writePetFavoriteSlugs(slugs: string[]): void {
  try {
    window.localStorage.setItem(FAVORITES_KEY, JSON.stringify(normalizeFavoriteSlugs(slugs)))
    notifyPetPreferences()
  } catch {
    /* ignore */
  }
}

export { MAX_FAVORITE_PETS }
