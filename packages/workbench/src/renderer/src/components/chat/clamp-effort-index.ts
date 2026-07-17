/** Tier keys aligned with reasoning-effort-selector.js `#tiers`. */
export const EFFORT_TIER_KEYS = ['Light', 'Medium', 'High', 'Extra High', 'Ultra'] as const

/**
 * Clamp a reasoning-effort slider index to 0..4.
 *
 * React 19 assigns custom-element props as strings via the property setter
 * (`el.value = "4"`). Coerce before `Number.isFinite` so Ultra is not
 * silently collapsed to the High default (2).
 */
export function clampEffortIndex(v: unknown): number {
  const n = typeof v === 'number' ? v : Number(v)
  return Math.min(4, Math.max(0, Number.isFinite(n) ? Math.round(n) : 2))
}

/** Mirror the web-component `value` setter used by React prop sync. */
export function effortValueAttribute(v: unknown): string {
  return String(clampEffortIndex(v))
}

export function effortTierKey(v: unknown): (typeof EFFORT_TIER_KEYS)[number] {
  return EFFORT_TIER_KEYS[clampEffortIndex(v)] ?? 'High'
}
