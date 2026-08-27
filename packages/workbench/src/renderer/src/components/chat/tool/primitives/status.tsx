import { memo } from 'react'
import { CheckCircle2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { cn } from '../cn'
import { ShimmerText } from './shimmer'
import type { ToolUIState } from '../render-context'

export interface ToolStatusIndicatorProps {
  state: ToolUIState
  className?: string
  showLabel?: boolean
  label?: string
}

/**
 * Trailing status cue. Apple-style restraint: no chromatic fills —
 * running shimmers, success is a quiet check, error is just "!".
 */
export const ToolStatusIndicator = memo(function ToolStatusIndicator({
  state,
  className,
  showLabel = false,
  label
}: ToolStatusIndicatorProps): React.JSX.Element {
  const { t } = useTranslation('common')
  const isLive = state === 'running' || state === 'awaiting_approval'
  const awaiting = state === 'awaiting_approval'
  const awaitingLabel = showLabel && label ? label : t('toolAwaitingApproval')

  return (
    <span
      className={cn('inline-flex items-center gap-1 text-ds-muted', className)}
      role={isLive ? 'status' : 'img'}
      aria-label={
        state === 'error'
          ? 'error'
          : state === 'success'
            ? 'success'
            : awaiting
              ? awaitingLabel
              : 'running'
      }
    >
      {awaiting ? (
        <span className="text-[0.5625rem] font-medium tracking-[0.02em] text-amber-700 dark:text-amber-400">
          {awaitingLabel}
        </span>
      ) : state === 'running' ? (
        <ShimmerText
          text={showLabel && label ? label : '…'}
          className="text-[0.5625rem] tracking-[0.05em] leading-none"
        />
      ) : state === 'error' ? (
        <span
          aria-hidden
          className="flex h-3.5 w-3.5 shrink-0 items-center justify-center text-[13px] font-semibold leading-none tracking-tight text-ds-ink/70"
        >
          !
        </span>
      ) : (
        <CheckCircle2 aria-hidden className="size-3 shrink-0 text-ds-ink/45" strokeWidth={1.9} />
      )}
      {showLabel && !isLive && label ? (
        <span aria-hidden className="text-[0.5625rem]">
          {label}
        </span>
      ) : null}
    </span>
  )
})
