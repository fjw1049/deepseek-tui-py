/**
 * Shared time-of-day buckets for greeting copy + weather sky glyph.
 *
 * 上午 → 中午 → 下午 → 傍晚 → 晚上 → 夜晚
 */

export type DayPart = 'morning' | 'noon' | 'afternoon' | 'dusk' | 'evening' | 'night'

export type DayPartRange = {
  id: DayPart
  /** Inclusive start hour (0–23). */
  startHour: number
  /** Exclusive end hour (0–24); wraps past midnight when end <= start. */
  endHour: number
}

/** Canonical schedule — keep preview HTML / docs in sync with this table. */
export const DAY_PART_RANGES: readonly DayPartRange[] = [
  { id: 'morning', startHour: 5, endHour: 11 },
  { id: 'noon', startHour: 11, endHour: 14 },
  { id: 'afternoon', startHour: 14, endHour: 17 },
  { id: 'dusk', startHour: 17, endHour: 19 },
  { id: 'evening', startHour: 19, endHour: 22 },
  { id: 'night', startHour: 22, endHour: 5 }
] as const

/** Resolve the active day-part for a local hour (0–23). */
export function dayPartFor(hour: number): DayPart {
  const h = ((Math.floor(hour) % 24) + 24) % 24
  if (h >= 5 && h < 11) return 'morning'
  if (h >= 11 && h < 14) return 'noon'
  if (h >= 14 && h < 17) return 'afternoon'
  if (h >= 17 && h < 19) return 'dusk'
  if (h >= 19 && h < 22) return 'evening'
  return 'night'
}

/** i18n key for the greeting headline, e.g. `greetingNoon`. */
export function greetingKeyForDayPart(part: DayPart): string {
  const suffix = part.charAt(0).toUpperCase() + part.slice(1)
  return `greeting${suffix}`
}

/** i18n key for the accent flair, e.g. `greetingFlairNoon`. */
export function greetingFlairKeyForDayPart(part: DayPart): string {
  const suffix = part.charAt(0).toUpperCase() + part.slice(1)
  return `greetingFlair${suffix}`
}

/** Human-readable hour window for UI/debug, e.g. `05:00 – 11:00`. */
export function formatDayPartRange(part: DayPart): string {
  const range = DAY_PART_RANGES.find((r) => r.id === part)
  if (!range) return ''
  const fmt = (h: number): string => `${String(h).padStart(2, '0')}:00`
  if (range.endHour <= range.startHour) {
    return `${fmt(range.startHour)} – ${fmt(range.endHour)}`
  }
  return `${fmt(range.startHour)} – ${fmt(range.endHour)}`
}
