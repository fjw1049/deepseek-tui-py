import type { ReactElement } from 'react'
import type { DiffStats } from '../lib/diff-stats'

type Props = {
  stats: DiffStats
  size?: 'sm' | 'md' | 'lg'
  className?: string
  /** Hide a side whose count is zero (matches the DiffView header). */
  hideZero?: boolean
}

export function ChangeDiffStatsLabel({
  stats,
  size = 'md',
  className = '',
  hideZero = false
}: Props): ReactElement {
  return (
    <span className={`ds-change-stats ds-change-stats--${size} ${className}`.trim()}>
      {!hideZero || stats.added > 0 ? (
        <span className="ds-change-stats__added">+{stats.added}</span>
      ) : null}
      {!hideZero || stats.removed > 0 ? (
        <span className="ds-change-stats__removed">-{stats.removed}</span>
      ) : null}
    </span>
  )
}
