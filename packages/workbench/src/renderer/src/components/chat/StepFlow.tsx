import { useState, type ReactElement, type ReactNode } from 'react'
import { ChevronDown } from 'lucide-react'
import { useTranslation } from 'react-i18next'

export type StepFlowStatus =
  | 'queued'
  | 'pending'
  | 'running'
  | 'ok'
  | 'failed'
  | 'cancelled'
  | 'completed'
  | 'skipped'
  | 'info'

export type StepFlowItem = {
  id: string
  status: StepFlowStatus
  /** One-line rail label, e.g. `step 3 · read_file · ok`. */
  label: string
  /** Optional secondary muted text (timestamp, …). */
  meta?: string
  input?: string | null
  output?: string | null
  /** Left indent level for tree nesting (0 = root). */
  depth?: number
}

const STATUS_STYLE: Record<
  StepFlowStatus,
  { ring: string; fill: string; pulse?: boolean }
> = {
  queued: {
    ring: 'border-ds-border-muted bg-ds-card',
    fill: 'bg-transparent'
  },
  pending: {
    ring: 'border-ds-border-muted bg-ds-card',
    fill: 'bg-transparent'
  },
  running: {
    ring: 'border-violet-400/70 bg-violet-500/10 dark:border-violet-400/50',
    fill: 'bg-violet-500',
    pulse: true
  },
  ok: {
    ring: 'border-emerald-400/60 bg-emerald-500/10',
    fill: 'bg-emerald-500'
  },
  completed: {
    ring: 'border-emerald-400/60 bg-emerald-500/10',
    fill: 'bg-emerald-500'
  },
  failed: {
    ring: 'border-rose-400/60 bg-rose-500/10',
    fill: 'bg-rose-500'
  },
  cancelled: {
    ring: 'border-ds-border-muted bg-ds-hover/50',
    fill: 'bg-ds-faint'
  },
  skipped: {
    ring: 'border-ds-border-muted bg-ds-hover/40',
    fill: 'bg-ds-faint'
  },
  info: {
    ring: 'border-ds-border-muted bg-ds-card',
    fill: 'bg-ds-muted'
  }
}

function StatusDot({
  status,
  isLast
}: {
  status: StepFlowStatus
  isLast: boolean
}): ReactElement {
  const style = STATUS_STYLE[status] ?? STATUS_STYLE.info
  return (
    <span className="relative flex w-4 shrink-0 flex-col items-center self-stretch pt-2">
      {!isLast ? (
        <span
          aria-hidden
          className="absolute bottom-0 top-6 w-px bg-ds-border-muted/70"
        />
      ) : null}
      <span
        className={[
          'relative z-[1] flex h-3.5 w-3.5 items-center justify-center rounded-full border',
          style.ring
        ].join(' ')}
      >
        <span
          className={[
            'h-1.5 w-1.5 rounded-full',
            style.fill,
            style.pulse ? 'animate-pulse' : ''
          ].join(' ')}
        />
      </span>
    </span>
  )
}

function summaryText(item: StepFlowItem): string | null {
  const out = item.output?.trim()
  if (out) return out
  const input = item.input?.trim()
  if (input) return input
  return null
}

function StepRow({
  item,
  isLast,
  compact
}: {
  item: StepFlowItem
  isLast: boolean
  compact?: boolean
}): ReactElement {
  const { t } = useTranslation('common')
  const [open, setOpen] = useState(false)
  const body = summaryText(item)
  const hasBody = Boolean(body)
  const depth = Math.max(0, item.depth ?? 0)

  return (
    <li
      className="relative flex gap-0"
      style={depth > 0 ? { marginLeft: `${depth * 0.75}rem` } : undefined}
    >
      <StatusDot status={item.status} isLast={isLast} />
      <div className="min-w-0 flex-1 pb-0.5">
        <button
          type="button"
          disabled={!hasBody}
          onClick={() => hasBody && setOpen((v) => !v)}
          aria-expanded={hasBody ? open : undefined}
          className={[
            'group flex w-full items-center gap-1.5 rounded-[10px] text-left transition-[background-color,transform] duration-150',
            compact ? 'px-1.5 py-1' : 'px-2 py-1.5',
            'active:scale-[0.995]',
            hasBody
              ? 'hover:bg-black/[0.03] dark:hover:bg-white/[0.04]'
              : 'cursor-default'
          ].join(' ')}
        >
          <span className="min-w-0 flex-1">
            {/* Keep the exact rail contract: step N · tool_name · ok/fail */}
            <span
              className={[
                'block truncate font-mono tracking-[-0.01em] text-ds-ink',
                compact ? 'text-[11.5px] leading-4' : 'text-[12.5px] leading-5'
              ].join(' ')}
            >
              {item.label}
            </span>
            {item.meta && !compact ? (
              <span className="mt-0.5 block truncate text-[10.5px] tabular-nums text-ds-faint">
                {formatMeta(item.meta)}
              </span>
            ) : null}
          </span>
          {hasBody ? (
            <ChevronDown
              className={[
                'h-3.5 w-3.5 shrink-0 text-ds-faint transition-transform duration-200 ease-out',
                open ? 'rotate-180' : 'rotate-0',
                'opacity-45 group-hover:opacity-75'
              ].join(' ')}
              strokeWidth={1.75}
            />
          ) : null}
        </button>

        <div
          className={[
            'grid transition-[grid-template-rows,opacity] duration-200 ease-out motion-reduce:transition-none',
            open && hasBody ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0'
          ].join(' ')}
        >
          <div className="min-h-0 overflow-hidden">
            {hasBody && body ? (
              <div className="mx-1 mb-1.5 overflow-hidden rounded-[12px] bg-black/[0.03] dark:bg-white/[0.04]">
                <div className="px-3 pb-1 pt-2 text-[10.5px] font-semibold tracking-[0.02em] text-ds-muted">
                  {t('stepFlowSummary', { defaultValue: '摘要' })}
                </div>
                <pre className="max-h-44 overflow-auto px-3 pb-2.5 font-mono text-[11.5px] leading-[1.45] text-ds-ink/90 whitespace-pre-wrap break-words">
                  {body}
                </pre>
                {item.input?.trim() && item.output?.trim() ? (
                  <details className="border-t border-ds-border/40 px-3 py-2">
                    <summary className="cursor-pointer text-[11px] font-medium text-ds-faint hover:text-ds-muted">
                      {t('stepFlowMoreDetail', { defaultValue: '输入 / 完整输出' })}
                    </summary>
                    <div className="mt-2 space-y-2">
                      <DetailBlock label={t('stepFlowInput', { defaultValue: 'Input' })}>
                        {item.input}
                      </DetailBlock>
                      <DetailBlock label={t('stepFlowOutput', { defaultValue: 'Output' })}>
                        {item.output}
                      </DetailBlock>
                    </div>
                  </details>
                ) : null}
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </li>
  )
}

function formatMeta(meta: string): string {
  const ms = Date.parse(meta)
  if (!Number.isNaN(ms)) {
    try {
      return new Date(ms).toLocaleTimeString(undefined, {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
      })
    } catch {
      return meta
    }
  }
  return meta
}

function DetailBlock({
  label,
  children
}: {
  label: string
  children: ReactNode
}): ReactElement {
  return (
    <div>
      <div className="mb-0.5 text-[10px] font-semibold text-ds-faint">{label}</div>
      <pre className="max-h-36 overflow-auto font-mono text-[11px] leading-[1.45] text-ds-ink/85 whitespace-pre-wrap break-words">
        {children}
      </pre>
    </div>
  )
}

export function StepFlow({
  items,
  emptyLabel,
  className,
  compact
}: {
  items: StepFlowItem[]
  emptyLabel?: string
  className?: string
  /** Tighter rows for inline panels under summary cards. */
  compact?: boolean
}): ReactElement {
  const { t } = useTranslation('common')
  if (items.length === 0) {
    return (
      <p className="px-1 py-2 text-[12.5px] leading-5 text-ds-faint">
        {emptyLabel ?? t('stepFlowEmpty', { defaultValue: 'No steps yet.' })}
      </p>
    )
  }
  return (
    <ol className={['flex flex-col', className ?? ''].join(' ')}>
      {items.map((item, index) => (
        <StepRow
          key={item.id}
          item={item}
          isLast={index === items.length - 1}
          compact={compact}
        />
      ))}
    </ol>
  )
}

/** Map common lifecycle strings onto StepFlowStatus. */
export function lifecycleToStepStatus(
  status: string | null | undefined
): StepFlowStatus {
  switch ((status || '').toLowerCase()) {
    case 'queued':
      return 'queued'
    case 'pending':
      return 'pending'
    case 'running':
      return 'running'
    case 'completed':
    case 'done':
    case 'success':
      return 'completed'
    case 'failed':
    case 'error':
    case 'timed_out':
      return 'failed'
    case 'cancelled':
    case 'canceled':
      return 'cancelled'
    case 'skipped':
      return 'skipped'
    default:
      return 'info'
  }
}
