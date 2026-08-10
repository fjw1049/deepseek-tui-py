import type { ReactElement } from 'react'
import type { KanbanColumnKey } from './kanban.logic'

/**
 * Static column glyphs (Linear-style). Never animate — headers are labels,
 * not loading indicators.
 */
export function KanbanStatusIcon({
  column,
  className = 'h-3.5 w-3.5'
}: {
  column: KanbanColumnKey
  className?: string
}): ReactElement {
  if (column === 'done') {
    return (
      <svg viewBox="0 0 14 14" className={`shrink-0 text-sky-500 ${className}`} aria-hidden>
        <circle cx="7" cy="7" r="7" fill="currentColor" />
        <path
          d="M4.1 7.4 6.15 9.4 9.9 4.9"
          fill="none"
          stroke="var(--ds-surface-card, #111)"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    )
  }

  if (column === 'inProgress') {
    // Half-filled pie — "in motion" without a perpetual spinner.
    return (
      <svg viewBox="0 0 14 14" className={`shrink-0 text-amber-400 ${className}`} aria-hidden>
        <circle cx="7" cy="7" r="6" fill="none" stroke="currentColor" strokeWidth="1.7" />
        <path d="M7 3.5 A3.5 3.5 0 0 1 7 10.5 Z" fill="currentColor" />
      </svg>
    )
  }

  // Draft: document with a folded corner — reads as "unsent note", not empty/loading.
  return (
    <svg viewBox="0 0 14 14" className={`shrink-0 text-ds-faint ${className}`} aria-hidden>
      <path
        d="M3.5 1.75h5.1L10.5 3.65v8.6H3.5V1.75Z"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.35"
        strokeLinejoin="round"
      />
      <path
        d="M8.55 1.75V3.7H10.5"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.35"
        strokeLinejoin="round"
      />
      <path
        d="M5.1 6.4h3.8M5.1 8.55h2.6"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.25"
        strokeLinecap="round"
      />
    </svg>
  )
}
