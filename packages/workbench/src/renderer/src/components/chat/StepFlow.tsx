import { useState, type ReactElement, type ReactNode } from 'react'
import { ChevronDown } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import {
  formatProbeComposeTitleSegment,
  probeComposeTitleIsFullyConcrete,
  probeComposeTitleSegments,
  probeKindLabelKey,
  type ProbeBatchCompose,
  type ProbeBatchEntry
} from '../../lib/step-flow-collapse'
import { humanizeToolName } from './tool/render-context'

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
  /** Primary rail title — humanized intent, e.g. `读取文件`. */
  label: string
  /** Optional target/query under the title, e.g. `…/StepFlow.tsx`. */
  detail?: string
  /** Optional tertiary muted text (step N, timestamp, …). */
  meta?: string
  input?: string | null
  output?: string | null
  /** Left indent level for tree nesting (0 = root). */
  depth?: number
  /**
   * `narration` — model preface; `batch` — folded consecutive probes
   * (main-chat toolBatchTitle).
   */
  variant?: 'narration' | 'batch'
  /** Raw tool name for collapse / batch i18n (e.g. read_file). */
  toolName?: string
  batchToolName?: string
  batchCount?: number
  /** True when the batch mixed different probe tools (read + search + …). */
  batchMixed?: boolean
  /** Per-kind counts for mixed-batch titles (`读 a.py · 搜 foo`). */
  batchCompose?: ProbeBatchCompose
  /** Typed targets for expand body / mixed-batch title. */
  batchEntries?: ProbeBatchEntry[]
}

const STATUS_STYLE: Record<
  StepFlowStatus,
  { ring: string; fill: string; pulse?: boolean; mark?: string }
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
    ring: 'border-ds-ink/35 bg-ds-hover',
    fill: 'bg-ds-ink/70',
    pulse: true
  },
  ok: {
    ring: 'border-ds-ink/25 bg-ds-hover/60',
    fill: 'bg-ds-ink/45'
  },
  completed: {
    ring: 'border-ds-ink/25 bg-ds-hover/60',
    fill: 'bg-ds-ink/45'
  },
  failed: {
    ring: 'border-ds-ink/40 bg-ds-hover',
    fill: 'bg-transparent',
    mark: '!'
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
        {style.mark ? (
          <span className="text-[9px] font-semibold leading-none text-ds-ink/75">{style.mark}</span>
        ) : (
          <span
            className={[
              'h-1.5 w-1.5 rounded-full',
              style.fill,
              style.pulse ? 'animate-pulse' : ''
            ].join(' ')}
          />
        )}
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

function batchComposeTitle(
  entries: ProbeBatchEntry[] | undefined,
  compose: ProbeBatchCompose | undefined,
  t: (key: string, opts?: Record<string, unknown>) => string
): { title: string; fullyConcrete: boolean } | null {
  const segments = probeComposeTitleSegments(entries ?? [], compose)
  if (segments.length === 0) return null
  return {
    title: segments.map((seg) => formatProbeComposeTitleSegment(seg, t)).join(' · '),
    fullyConcrete: probeComposeTitleIsFullyConcrete(segments)
  }
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
  const isNarration = item.variant === 'narration'
  const isBatch = item.variant === 'batch'
  const batchTool = item.batchToolName || item.toolName || ''
  // Compose titles are only for mixed probe runs; same-tool batches keep
  // “读取文件 · N 项” with targets in the subtitle preview.
  const compose =
    isBatch && item.batchMixed
      ? batchComposeTitle(item.batchEntries, item.batchCompose, t)
      : null
  const batchLabel = compose
    ? compose.title
    : item.batchMixed
      ? t('toolBatchProbeLabel')
      : humanizeToolName(batchTool) || item.label || batchTool
  const title = isBatch
    ? compose
      ? batchLabel
      : t('toolBatchTitle', {
          label: batchLabel,
          count: item.batchCount ?? 0
        })
    : item.label
  const titleUsesTargets = Boolean(compose?.fullyConcrete)
  const batchPreview =
    isBatch && !titleUsesTargets && item.detail?.trim()
      ? item.detail.trim()
      : isBatch && !titleUsesTargets && item.batchEntries?.length
        ? item.batchEntries
            .map((e) => e.target)
            .filter(Boolean)
            .join(' · ')
        : ''
  const batchEntries = item.batchEntries
  // Narration already shows its full line on the rail; only expand when the
  // stored body is meaningfully longer than the visible label.
  const body = isBatch && batchEntries && batchEntries.length > 0 ? null : summaryText(item)
  const hasTypedBatch = Boolean(isBatch && batchEntries && batchEntries.length > 0)
  const hasBody = Boolean(
    hasTypedBatch ||
      (body && (isBatch || !isNarration || body.trim() !== item.label.trim()))
  )
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
            <span
              className={[
                'block tracking-[-0.01em]',
                isNarration
                  ? [
                      'line-clamp-3 text-ds-faint/90',
                      compact
                        ? 'text-[12px] leading-5'
                        : 'text-[13.5px] leading-6'
                    ].join(' ')
                  : isBatch
                    ? [
                        'truncate text-ds-muted',
                        compact
                          ? 'text-[12px] leading-5'
                          : 'text-[13px] leading-5'
                      ].join(' ')
                    : [
                        'truncate text-ds-ink',
                        compact
                          ? 'text-[11.5px] leading-4'
                          : 'text-[12.5px] leading-5'
                      ].join(' ')
              ].join(' ')}
              title={isBatch ? title : undefined}
            >
              {title}
            </span>
            {isBatch && batchPreview && !open ? (
              <span
                className={[
                  'mt-0.5 block truncate text-ds-faint',
                  compact ? 'text-[10.5px] leading-4' : 'text-[11px] leading-4'
                ].join(' ')}
                title={batchPreview}
              >
                {batchPreview}
              </span>
            ) : null}
            {item.detail && !isBatch ? (
              <span
                className={[
                  'mt-0.5 block truncate text-ds-muted',
                  compact ? 'text-[10.5px] leading-4' : 'text-[11px] leading-4'
                ].join(' ')}
                title={item.detail}
              >
                {item.detail}
              </span>
            ) : null}
            {item.meta && !compact && !isNarration && !isBatch ? (
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
            {hasTypedBatch && open ? (
              <div className="mx-1 mb-1.5 overflow-hidden rounded-[12px] bg-black/[0.03] dark:bg-white/[0.04]">
                <ul className="max-h-44 overflow-auto px-3 py-2">
                  {batchEntries!.map((entry, idx) => (
                    <li
                      key={`${entry.toolName}-${idx}-${entry.target}`}
                      className="flex gap-2 py-0.5 text-[11.5px] leading-[1.45]"
                    >
                      <span className="shrink-0 font-medium text-ds-faint">
                        {t(probeKindLabelKey(entry.kind))}
                      </span>
                      <span className="min-w-0 break-words text-ds-ink/90">
                        {entry.target || '—'}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            {!hasTypedBatch && hasBody && body ? (
              <div className="mx-1 mb-1.5 overflow-hidden rounded-[12px] bg-black/[0.03] dark:bg-white/[0.04]">
                <div className="px-3 pb-1 pt-2 text-[10.5px] font-semibold tracking-[0.02em] text-ds-muted">
                  {t('stepFlowSummary')}
                </div>
                <pre className="max-h-44 overflow-auto px-3 pb-2.5 font-mono text-[11.5px] leading-[1.45] text-ds-ink/90 whitespace-pre-wrap break-words">
                  {body}
                </pre>
                {item.input?.trim() && item.output?.trim() ? (
                  <details className="border-t border-ds-border/40 px-3 py-2">
                    <summary className="cursor-pointer text-[11px] font-medium text-ds-faint hover:text-ds-muted">
                      {t('stepFlowMoreDetail')}
                    </summary>
                    <div className="mt-2 space-y-2">
                      <DetailBlock label={t('stepFlowInput')}>
                        {item.input}
                      </DetailBlock>
                      <DetailBlock label={t('stepFlowOutput')}>
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
        {emptyLabel ?? t('stepFlowEmpty')}
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
