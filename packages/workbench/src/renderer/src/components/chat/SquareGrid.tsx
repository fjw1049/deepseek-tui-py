import type { ReactElement } from 'react'

type Props = {
  className?: string
  /** Visual footprint. `sm` ≈ 14px (thinking lines), `md` ≈ 16px (turn chrome). */
  size?: 'sm' | 'md'
  /**
   * When false, cells stay still (no wave). Prefer unmounting when idle;
   * this is a safety net if a parent leaves the icon mounted.
   */
  active?: boolean
}

/**
 * 2×2 Square Grid loader (Amicro-style): staggered scale/opacity wave.
 * Pure CSS — no Motion dependency. Color via `currentColor`.
 * Animate only while `active` — finished turns must not keep pulsing.
 */
export function SquareGrid({
  className = '',
  size = 'sm',
  active = true
}: Props): ReactElement {
  return (
    <span
      className={[
        'ds-square-grid',
        size === 'md' ? 'ds-square-grid--md' : '',
        active ? '' : 'ds-square-grid--static',
        className
      ]
        .filter(Boolean)
        .join(' ')}
      aria-hidden
    >
      {Array.from({ length: 4 }, (_, i) => (
        <span key={i} className="ds-square-grid__cell" />
      ))}
    </span>
  )
}
