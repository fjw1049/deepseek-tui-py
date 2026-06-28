import type { LucideIcon } from 'lucide-react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { cn } from '../cn'
import { ToolStatusIndicator } from './status'
import type { ToolUIState } from '../render-context'

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
}

/**
 * Compact, always-visible header row for a tool card. Layout: icon · label ·
 * descriptor · status · chevron. The chevron only shows on hover when collapsed
 * so the row stays calm unless the user is about to act on it.
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
  titleClassName
}: ToolHeaderRowProps): React.JSX.Element {
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
