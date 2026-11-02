const ENABLED_KEY = 'deepseekgui.pet.enabled'
const SLUG_KEY = 'deepseekgui.pet.slug'
const CHATTER_KEY = 'deepseekgui.pet.chatter'
const AI_LINES_KEY = 'deepseekgui.pet.aiLines'
// v2: offset left of the dock's right end (v1 was centred, so its values no longer apply).
const DOCK_X_KEY = 'deepseekgui.pet.dockX.v2'

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

/** Off leaves only the bubbles that ask the person for something. */
export function readPetChatter(): boolean {
  try {
    return window.localStorage.getItem(CHATTER_KEY) !== '0'
  } catch {
    return true
  }
}

export function writePetChatter(enabled: boolean): void {
  try {
    window.localStorage.setItem(CHATTER_KEY, enabled ? '1' : '0')
    notifyPetPreferences()
  } catch {
    /* ignore */
  }
}

/** Off by default: each line costs tokens and sends a reply excerpt to the provider. */
export function readPetAiLines(): boolean {
  try {
    return window.localStorage.getItem(AI_LINES_KEY) === '1'
  } catch {
    return false
  }
}

export function writePetAiLines(enabled: boolean): void {
  try {
    window.localStorage.setItem(AI_LINES_KEY, enabled ? '1' : '0')
    notifyPetPreferences()
  } catch {
    /* ignore */
  }
}

export function readPetDockX(): number {
  try {
    const value = Number(window.localStorage.getItem(DOCK_X_KEY))
    return Number.isFinite(value) ? Math.min(0, value) : 0
  } catch {
    return 0
  }
}

export function writePetDockX(x: number): void {
  try {
    window.localStorage.setItem(DOCK_X_KEY, String(Math.round(x)))
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
