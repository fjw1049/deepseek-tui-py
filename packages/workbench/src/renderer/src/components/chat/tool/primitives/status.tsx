import { memo } from 'react'
import { AlertCircle, CheckCircle2, Loader2 } from 'lucide-react'
import { cn } from '../cn'
import { ShimmerText } from './shimmer'
import type { ToolUIState } from '../render-context'

export interface ToolStatusIndicatorProps {
  state: ToolUIState
  className?: string
  showLabel?: boolean
  label?: string
}

interface StateMeta {
  Icon: typeof Loader2
  tone: string
  shimmer: boolean
  spin?: boolean
}

const STATE_META: Record<ToolUIState, StateMeta> = {
  running: { Icon: Loader2, tone: 'text-amber-600 dark:text-amber-300', shimmer: true, spin: true },
  success: { Icon: CheckCircle2, tone: 'text-emerald-500/85', shimmer: false },
  error: { Icon: AlertCircle, tone: 'text-red-500', shimmer: false }
}

export const ToolStatusIndicator = memo(function ToolStatusIndicator({
  state,
  className,
  showLabel = false,
  label
}: ToolStatusIndicatorProps): React.JSX.Element {
  const meta = STATE_META[state]
  const Icon = meta.Icon
  const isLive = meta.shimmer

  return (
    <span
      className={cn('inline-flex items-center gap-1', meta.tone, className)}
      role={isLive ? 'status' : 'img'}
    >
      {meta.shimmer ? (
        <ShimmerText
          text={showLabel && label ? label : '…'}
          className="text-[0.5625rem] tracking-[0.05em] leading-none"
        />
      ) : (
        <Icon aria-hidden className={cn('size-3 shrink-0', meta.spin && 'animate-spin')} />
      )}
      {showLabel && !meta.shimmer && label ? (
        <span aria-hidden className="text-[0.5625rem]">
          {label}
        </span>
      ) : null}
    </span>
  )
})
