import { cn } from '../cn'

export interface ShimmerTextProps {
  text: string
  className?: string
}

/**
 * Animated shimmering text for live/pending states. Reuses the existing
 * `ds-shiny-text` keyframe already defined in index.css so it stays in sync
 * with the rest of the work-process chrome.
 */
export function ShimmerText({ text, className }: ShimmerTextProps): React.JSX.Element {
  return <span className={cn('ds-shiny-text', className)}>{text}</span>
}
