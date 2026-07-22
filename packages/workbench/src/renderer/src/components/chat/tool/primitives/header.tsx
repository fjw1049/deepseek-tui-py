import type { LucideIcon } from 'lucide-react'
import { ChevronDown, ChevronRight, FileCode } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { cn } from '../cn'
import { ToolStatusIndicator } from './status'
import type { ToolUIState } from '../render-context'
import { ChangeDiffStatsLabel } from '../../../ChangeDiffStatsLabel'
import type { DiffStats } from '../../../../lib/diff-stats'

export interface ToolHeaderRowProps {
  icon?: LucideIcon
  label: string
  title?: string
  subtitle?: string
  state: ToolUIState
  expanded: boolean
  canExpand: boolean
  className?: string
  labelClassName?: string
  titleClassName?: string
  /** Per-edit +N/-N shown next to the descriptor (file mutations). */
  diffStats?: DiffStats
  /** Open the edited file in the workspace editor (at the first changed line). */
  onOpenInEditor?: () => void
}

/**
 * Compact, always-visible header row for a tool card. Layout: icon · label ·
 * descriptor · diff stats · open-in-editor · status · chevron. The chevron and
 * the open-in-editor button only show on hover when collapsed so the row stays
 * calm unless the user is about to act on it.
 */
export function ToolHeaderRow({
  icon: Icon,
  label,
  title,
  subtitle,
  state,
  expanded,
  canExpand,
  className,
  labelClassName,
  titleClassName,
  diffStats,
  onOpenInEditor
}: ToolHeaderRowProps): React.JSX.Element {
  const { t } = useTranslation('common')
  return (
    <div className={cn('flex w-full items-center gap-2', className)}>
      {Icon ? (
        <Icon className="h-3.5 w-3.5 shrink-0 text-ds-faint" strokeWidth={1.8} aria-hidden />
      ) : null}
      <span
        className={cn(
          'shrink-0 font-mono text-[0.6875rem] font-medium text-ds-muted',
          labelClassName
        )}
      >
        {label}
      </span>
      {title ? (
        <span
          className={cn(
            'min-w-0 flex-1 truncate text-[13px] tabular-nums text-ds-faint',
            titleClassName
          )}
          title={subtitle ?? title}
        >
          {title}
        </span>
      ) : (
        <span className="flex-1" />
      )}
      {diffStats ? (
        <ChangeDiffStatsLabel stats={diffStats} size="sm" hideZero className="shrink-0" />
      ) : null}
      {onOpenInEditor ? (
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation()
            onOpenInEditor()
          }}
          title={t('inspectorOpenInEditor')}
          aria-label={t('inspectorOpenInEditor')}
          className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-md text-ds-faint opacity-0 transition hover:bg-ds-hover hover:text-ds-ink focus-visible:opacity-100 group-hover:opacity-100"
        >
          <FileCode className="h-3.5 w-3.5" strokeWidth={1.85} />
        </button>
      ) : null}
      <ToolStatusIndicator state={state} />
      {canExpand ? (
        expanded ? (
          <ChevronDown className="h-3 w-3 shrink-0 opacity-45" strokeWidth={1.8} />
        ) : (
          <ChevronRight
            className="h-3 w-3 shrink-0 opacity-0 transition group-hover:opacity-45"
            strokeWidth={1.8}
          />
        )
      ) : null}
    </div>
  )
}
