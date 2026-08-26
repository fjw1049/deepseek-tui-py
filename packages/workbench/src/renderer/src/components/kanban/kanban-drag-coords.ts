import type { Modifier } from '@dnd-kit/core'

/** body uses `zoom: var(--ds-ui-scale)`; layout px ≠ getBoundingClientRect px. */
export function readKanbanUiScale(): number {
  const n = parseFloat(
    getComputedStyle(document.documentElement).getPropertyValue('--ds-ui-scale')
  )
  return Number.isFinite(n) && n > 0 ? n : 1
}

/** Visual (client / getBoundingClientRect) px → CSS px on a zoomed body. */
export function layoutPxFromVisual(visualPx: number, scale: number): number {
  const factor = scale > 0 ? scale : 1
  return visualPx / factor
}

export function scaleDndTransform<T extends { x: number; y: number }>(
  transform: T,
  scale: number
): T {
  if (scale === 1 || scale <= 0) return transform
  return { ...transform, x: transform.x / scale, y: transform.y / scale }
}

/** Keep dnd-kit's own overlay motion; only undo body zoom on the delta. */
export const adjustKanbanOverlayForUiScale: Modifier = ({ transform }) =>
  scaleDndTransform(transform, readKanbanUiScale())
