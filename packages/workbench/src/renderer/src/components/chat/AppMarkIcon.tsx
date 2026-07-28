import type { ReactElement } from 'react'

type Props = {
  className?: string
  /**
   * Visual footprint. `sm` ≈ 14px (thinking lines), `md` ≈ 18px (turn chrome).
   * Pass `false` when sizing via `className` (e.g. empty-stage hero).
   */
  size?: 'sm' | 'md' | false
  /** When false, freeze on the rest pose (large TL / small BR). */
  active?: boolean
}

/**
 * Animated brand mark matching `app-icon.svg`:
 * largest (TL) ↔ smallest (BR) swap along the diagonal.
 * Mid grays stay put. Color travels with each square.
 *
 * Div geometry (not SVG CSS transforms) so motion stays correct at 14–18px.
 */
export function AppMarkIcon({
  className = '',
  size = 'sm',
  active = true
}: Props): ReactElement {
  const sizeClass =
    size === 'md' ? 'ds-app-mark--md' : size === 'sm' ? 'ds-app-mark--sm' : ''
  return (
    <span
      className={[
        'ds-app-mark',
        sizeClass,
        active ? '' : 'ds-app-mark--static',
        className
      ]
        .filter(Boolean)
        .join(' ')}
      aria-hidden
    >
      <span className="ds-app-mark__cell ds-app-mark__cell--mid-tr" />
      <span className="ds-app-mark__cell ds-app-mark__cell--mid-bl" />
      <span className="ds-app-mark__cell ds-app-mark__cell--swap ds-app-mark__cell--large" />
      <span className="ds-app-mark__cell ds-app-mark__cell--swap ds-app-mark__cell--small" />
    </span>
  )
}
