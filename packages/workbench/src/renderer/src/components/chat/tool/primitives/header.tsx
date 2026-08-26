import type { LucideIcon } from 'lucide-react'
import { ChevronDown, ChevronRight, FileCode } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { cn } from '../cn'
import { FileChip } from '../../FileChip'
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
  /** When set, render a clickable file chip instead of the plain title. */
  filePath?: string
  fileLine?: number
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
  onOpenInEditor,
  filePath,
  fileLine
}: ToolHeaderRowProps): React.JSX.Element {
  const { t } = useTranslation('common')
  return (
    <div className={cn('ds-tool-header-row flex w-full min-w-0 items-center', className)}>
      <span className="ds-tool-header-row__lead min-w-0 flex-1">
        {Icon ? (
          <Icon className="ds-tool-header-row__icon shrink-0 text-ds-faint" strokeWidth={1.8} aria-hidden />
        ) : (
          <span className="ds-tool-header-row__icon shrink-0" aria-hidden />
        )}
        <span
          className={cn(
            'ds-tool-header-row__label shrink-0 font-mono font-medium text-ds-muted',
            labelClassName
          )}
        >
          {label}
        </span>
        {filePath ? (
          <span className="ds-tool-header-row__main min-w-0">
            <FileChip path={filePath} line={fileLine} skipValidation variant="list" />
          </span>
        ) : title ? (
          <span
            className={cn(
              'ds-tool-header-row__title ds-tool-header-row__main min-w-0 truncate tabular-nums text-ds-faint',
              titleClassName
            )}
            title={subtitle ?? title}
          >
            {title}
          </span>
        ) : null}
      </span>
      <span className="ds-tool-header-row__meta">
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
            className="ds-tool-header-row__action inline-flex shrink-0 items-center justify-center rounded-md text-ds-faint opacity-0 transition hover:bg-ds-hover hover:text-ds-ink focus-visible:opacity-100 group-hover:opacity-100"
          >
            <FileCode strokeWidth={1.85} />
          </button>
        ) : null}
        <ToolStatusIndicator state={state} className="ds-tool-header-row__status" />
        <span className="ds-tool-header-row__chevron" aria-hidden>
          {canExpand ? (
            expanded ? (
              <ChevronDown strokeWidth={1.8} />
            ) : (
              <ChevronRight className="opacity-0 transition group-hover:opacity-45" strokeWidth={1.8} />
            )
          ) : null}
        </span>
      </span>
    </div>
  )
}
