import type { PetTurnDigest } from './pet-turn-digest'

export type PetBubbleReason =
  | 'turn_done'
  | 'turn_recovered'
  | 'turn_failed'
  | 'stream_error'
  | 'tests_failed'
  | 'large_diff'
  | 'petted'
  | 'named'

export const PET_BUBBLE_SHOW_MS = 10_000
export const PET_BUBBLE_COOLDOWN_MS = 30_000
export const PET_LONG_TURN_MS = 30_000
export const PET_LARGE_DIFF_LINES = 80
export const PET_WAITING_NUDGE_MS = 120_000
const RECENT_LINES = 3

/** These matter enough, or were asked for, so the chatter cooldown does not apply. */
const SKIPS_COOLDOWN: ReadonlySet<PetBubbleReason> = new Set([
  'turn_failed', 'stream_error', 'tests_failed', 'large_diff', 'petted', 'named'
])

const LINE_KEYS: Record<PetBubbleReason, readonly string[]> = {
  turn_done: ['petLineDone1', 'petLineDone2', 'petLineDone3'],
  turn_recovered: ['petLineRecovered1', 'petLineRecovered2'],
  turn_failed: ['petLineFailed1', 'petLineFailed2'],
  stream_error: ['petLineStreamError1'],
  tests_failed: ['petLineTestsFailed1', 'petLineTestsFailed2'],
  large_diff: ['petLineLargeDiff1', 'petLineLargeDiff2'],
  petted: ['petLinePetted1', 'petLinePetted2', 'petLinePetted3', 'petLinePetted4'],
  named: ['petLineNamed1', 'petLineNamed2', 'petLineNamed3']
}

export function canPetSpeak(reason: PetBubbleReason, lastSpokeAt: number, now: number): boolean {
  return SKIPS_COOLDOWN.has(reason) || now - lastSpokeAt >= PET_BUBBLE_COOLDOWN_MS
}

export function pickPetLineKey(
  reason: PetBubbleReason,
  recent: readonly string[],
  random: () => number = Math.random
): string {
  const keys = LINE_KEYS[reason]
  const fresh = keys.filter((key) => !recent.includes(key))
  const pool = fresh.length ? fresh : keys
  return pool[Math.floor(random() * pool.length)] ?? keys[0]!
}

export function rememberPetLine(recent: readonly string[], line: string): string[] {
  return [...recent, line].slice(-RECENT_LINES)
}

export function bubbleReasonForTurn(digest: PetTurnDigest): PetBubbleReason | null {
  if (digest.outcome === 'cancelled') return null
  if (digest.outcome === 'failed') return 'turn_failed'
  if (digest.testsFailed) return 'tests_failed'
  if (digest.diffLines > PET_LARGE_DIFF_LINES) return 'large_diff'
  if (digest.toolErrors > 0) return 'turn_recovered'
  return digest.durationMs >= PET_LONG_TURN_MS ? 'turn_done' : null
}

/** `\b` fails next to CJK ("boba你好"), so Latin names are bounded by hand. */
export function mentionsPetName(text: string, name: string): boolean {
  const clean = name.trim()
  if (!clean) return false
  if (!/^[\x20-\x7e]+$/.test(clean)) return text.includes(clean)
  const escaped = clean.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return new RegExp(`(?<![A-Za-z0-9_])${escaped}(?![A-Za-z0-9_])`, 'i').test(text)
}
