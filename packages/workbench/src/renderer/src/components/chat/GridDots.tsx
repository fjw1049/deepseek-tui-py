import type { ReactElement } from 'react'

type Props = {
  className?: string
  /** Visual footprint. `sm` ≈ 14px (thinking lines), `md` ≈ 16px (turn chrome). */
  size?: 'sm' | 'md'
}

/**
 * 3×3 Grid Dots loader (Amicro-style): staggered scale/opacity wave.
 * Pure CSS — no Motion dependency. Color via `currentColor`.
 */
export function GridDots({ className = '', size = 'sm' }: Props): ReactElement {
  return (
    <span
      className={['ds-grid-dots', size === 'md' ? 'ds-grid-dots--md' : '', className]
        .filter(Boolean)
        .join(' ')}
      aria-hidden
    >
      {Array.from({ length: 9 }, (_, i) => (
        <span key={i} className="ds-grid-dots__dot" />
      ))}
    </span>
  )
}
