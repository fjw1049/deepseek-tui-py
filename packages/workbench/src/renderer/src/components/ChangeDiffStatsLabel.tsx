import type { ReactElement } from 'react'
import type { DiffStats } from '../lib/diff-stats'

type Props = {
  stats: DiffStats
  size?: 'sm' | 'md' | 'lg'
  className?: string
}

export function ChangeDiffStatsLabel({
  stats,
  size = 'md',
  className = ''
}: Props): ReactElement {
  return (
    <span className={`ds-change-stats ds-change-stats--${size} ${className}`.trim()}>
      <span className="ds-change-stats__added">+{stats.added}</span>
      <span className="ds-change-stats__removed">-{stats.removed}</span>
    </span>
  )
}
