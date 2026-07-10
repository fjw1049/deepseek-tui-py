// FILE: queryTrail.logic.ts
// Purpose: Pure helpers for the left-edge query navigation trail — project the
//   chat blocks into one tick per sent query and resolve which tick is active.
//   Ported from synara's messageTrail.logic.ts (macOS-Dock-style magnification).
// Depends on: ChatBlock shape only — no React, no DOM.

import type { ChatBlock } from '../../agent/types'
import { parseUserFocusPrefix } from '../../lib/user-focus-prefix'

/** One tick on the navigation trail — a single query the user sent. */
export interface QueryTrailItem {
  id: string
  /** 1-based position among sent queries, used for labels/aria. */
  ordinal: number
  /** Whitespace-normalized, length-capped text for the hover preview (the sent query). */
  preview: string
  /**
   * Whitespace-normalized, length-capped start of the turn's final assistant
   * message — the muted second line in the hover card. Empty when the turn has
   * produced no assistant text yet.
   */
  responsePreview: string
}

/** Snapshot of which trail tick is the reading anchor and which are in view. */
export interface ActiveTrailSnapshot {
  currentId: string | null
  visibleIds: readonly string[]
}

const EMPTY_ACTIVE_TRAIL_SNAPSHOT: ActiveTrailSnapshot = { currentId: null, visibleIds: [] }

function areActiveTrailSnapshotsEqual(
  a: ActiveTrailSnapshot,
  b: ActiveTrailSnapshot
): boolean {
  if (a.currentId !== b.currentId) return false
  if (a.visibleIds === b.visibleIds) return true
  if (a.visibleIds.length !== b.visibleIds.length) return false
  for (let i = 0; i < a.visibleIds.length; i += 1) {
    if (a.visibleIds[i] !== b.visibleIds[i]) return false
  }
  return true
}

/** External store for trail highlights so scroll-spy can update only the rail, not the timeline. */
export interface ActiveTrailStore {
  get: () => ActiveTrailSnapshot
  set: (value: ActiveTrailSnapshot | null) => void
  subscribe: (listener: () => void) => () => void
}

export function createActiveTrailStore(): ActiveTrailStore {
  let current: ActiveTrailSnapshot = EMPTY_ACTIVE_TRAIL_SNAPSHOT
  const listeners = new Set<() => void>()
  return {
    get: () => current,
    set: (value) => {
      const next = value ?? EMPTY_ACTIVE_TRAIL_SNAPSHOT
      if (areActiveTrailSnapshotsEqual(next, current)) return
      current = next
      for (const listener of listeners) listener()
    },
    subscribe: (listener) => {
      listeners.add(listener)
      return () => {
        listeners.delete(listener)
      }
    }
  }
}

/** Hard cap so a pathological paste can't bloat the hover-card payload. */
const MAX_PREVIEW_LENGTH = 280

function normalizePreview(text: string): string {
  const collapsed = text.replace(/\s+/g, ' ').trim()
  return collapsed.length > MAX_PREVIEW_LENGTH
    ? `${collapsed.slice(0, MAX_PREVIEW_LENGTH).trimEnd()}…`
    : collapsed
}

/**
 * Project the chat blocks into one trail item per user query, in transcript
 * order. Each item also carries the start of its turn's *final* assistant
 * message (the muted second line). Every non-empty assistant row overwrites its
 * response so the last one (the end-of-turn reply) wins. Non-message rows are
 * skipped; a turn with no assistant text yet keeps an empty `responsePreview`.
 */
export function deriveQueryTrailItems(blocks: readonly ChatBlock[]): QueryTrailItem[] {
  const items: QueryTrailItem[] = []
  let currentTurnIndex = -1
  for (const block of blocks) {
    if (block.kind === 'user') {
      const focus = parseUserFocusPrefix(block.text)
      const previewSource = focus ? focus.body || focus.name : block.text
      items.push({
        id: block.id,
        ordinal: items.length + 1,
        preview: normalizePreview(previewSource),
        responsePreview: ''
      })
      currentTurnIndex = items.length - 1
    } else if (block.kind === 'assistant' && currentTurnIndex >= 0) {
      const responsePreview = normalizePreview(block.text)
      if (responsePreview !== '') {
        items[currentTurnIndex]!.responsePreview = responsePreview
      }
    }
  }
  return items
}

/** Clamp `value` into `[min, max]`, finite-safe (returns `min` if range inverted). */
export function clampNumber(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) return min
  if (max < min) return min
  return value < min ? min : value > max ? max : value
}

/** Fixed vertical layout of the ticks; widths never affect these positions. */
export interface TrailGeometry {
  /** Vertical centre (px) of the first tick. */
  startY: number
  /** Centre-to-centre distance (px); 0 when there is a single tick. */
  spacing: number
  /** Vertical centre (px) of every tick, in order. */
  centerYs: number[]
  /** Total content height (px): `2*padding + (count-1)*spacing`. */
  contentHeight: number
}

/**
 * Lay the ticks out top-down at a fixed `spacingPx`, in their own content space.
 * The layout depends only on the query count — never on the measured viewport —
 * so the rail can cap + scroll its viewport without a size→layout→size loop.
 * Returns `null` for N=0 so the caller can skip all pointer handling.
 */
export function computeTrailGeometry(input: {
  count: number
  spacingPx?: number
  paddingPx?: number
}): TrailGeometry | null {
  const count = input.count
  const spacing = count <= 1 ? 0 : (input.spacingPx ?? 10)
  const padding = input.paddingPx ?? 12
  if (count <= 0) return null
  const centerYs: number[] = []
  for (let i = 0; i < count; i += 1) {
    centerYs.push(padding + i * spacing)
  }
  return {
    startY: padding,
    spacing,
    centerYs,
    contentHeight: 2 * padding + (count - 1) * spacing
  }
}

/**
 * Gaussian sigma tied to tick density so the focus radius stays ~1.5 ticks
 * whether the rail is sparse or dense: `clamp(spacing*1.5, min(spacing*2, 8), 22)`.
 */
export function computeSigma(spacing: number): number {
  return clampNumber(spacing * 1.5, Math.min(spacing * 2, 8), 22)
}

/** Per-tick Gaussian weight in `[0, 1]`; exactly `1` for the tick under the pointer. */
export function computeGaussianWeights(
  centerYs: readonly number[],
  pointerY: number,
  sigma: number
): number[] {
  if (sigma <= 0) {
    return centerYs.map((centerY) => (centerY === pointerY ? 1 : 0))
  }
  const twoSigmaSquared = 2 * sigma * sigma
  return centerYs.map((centerY) => {
    const distance = centerY - pointerY
    return Math.exp(-(distance * distance) / twoSigmaSquared)
  })
}

/** Resolved width/opacity for one tick. */
export interface TickStyle {
  width: number
  opacity: number
}

/**
 * Map Gaussian weights to width only — opacity stays a fixed per-state value.
 * Width lerps `baseW → effectiveMaxW` with the weight (the Dock size effect);
 * the anchor tick keeps `anchorOpacity`, everything else `restOpacity`.
 */
export function computeTickStyles(
  weights: readonly number[],
  currentAnchorIndex: number | null,
  baseW: number,
  effectiveMaxW: number,
  restOpacity: number,
  anchorOpacity: number
): TickStyle[] {
  return weights.map((weight, index) => ({
    width: baseW + (effectiveMaxW - baseW) * weight,
    opacity: index === currentAnchorIndex ? anchorOpacity : restOpacity
  }))
}

/** Rest-state styles (pointer away): all `baseW`, anchor brightened. */
export function computeRestStyles(
  count: number,
  currentAnchorIndex: number | null,
  baseW: number,
  restOpacity: number,
  anchorOpacity: number
): TickStyle[] {
  const styles: TickStyle[] = []
  for (let i = 0; i < count; i += 1) {
    styles.push({ width: baseW, opacity: i === currentAnchorIndex ? anchorOpacity : restOpacity })
  }
  return styles
}

/**
 * Index of the tick nearest `pointerY`. Clamps `pointerY` into the tick range
 * first so positions above/below the rail resolve to the first/last tick.
 * Always returns `0` for a single/degenerate rail. Finite-safe.
 */
export function computeFocusedIndex(pointerY: number, geometry: TrailGeometry): number {
  const count = geometry.centerYs.length
  if (count <= 1 || geometry.spacing === 0) return 0
  if (!Number.isFinite(pointerY)) return 0
  const endY = geometry.startY + (count - 1) * geometry.spacing
  const clampedY = clampNumber(pointerY, geometry.startY, endY)
  const raw = Math.round((clampedY - geometry.startY) / geometry.spacing)
  return clampNumber(raw, 0, count - 1)
}

/**
 * Keep the focused-query tooltip fully on-screen by clamping its vertical centre
 * into `[tooltipH/2 + margin, railH - tooltipH/2 - margin]` (caller keeps a
 * `translateY(-50%)`). Range-safe when the rail is shorter than the tooltip.
 */
export function clampTooltipTop(
  centerY: number,
  tooltipH: number,
  railH: number,
  margin = 4
): number {
  const half = tooltipH / 2 + margin
  return clampNumber(centerY, half, Math.max(half, railH - half))
}
