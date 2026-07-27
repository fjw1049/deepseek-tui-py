/** Context-window bounds for provider models (tokens). */

export const CUSTOM_MODEL_CONTEXT_WINDOW_DEFAULT = 500_000
export const CUSTOM_MODEL_CONTEXT_WINDOW_MIN = 1_000
export const CUSTOM_MODEL_CONTEXT_WINDOW_MAX = 1_000_000

export function normalizeCustomModelContextWindow(value: unknown): number {
  const parsed = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(parsed) || parsed <= 0) return CUSTOM_MODEL_CONTEXT_WINDOW_DEFAULT
  return Math.min(
    CUSTOM_MODEL_CONTEXT_WINDOW_MAX,
    Math.max(CUSTOM_MODEL_CONTEXT_WINDOW_MIN, Math.floor(parsed))
  )
}
