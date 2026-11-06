import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactElement
} from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { ChatBlock } from '../../agent/types'
import {
  contextBucketTokens,
  fallbackContextBreakdown,
  formatTokenCount,
  isContextBreakdown,
  snapshotFromContextBreakdown,
  type ContextBreakdownJson
} from '../../lib/estimate-context-usage'
import { useLightDismiss } from '../../hooks/use-light-dismiss'

type Props = {
  blocks: ChatBlock[]
  model: string
  hasActiveThread: boolean
  threadId?: string | null
  busy?: boolean
}

type BreakdownRow = {
  key: string
  label: string
  tokens: number
  color: string
}

function compactTokens(tokens: number): string {
  return formatTokenCount(tokens).replace(/\.0([kM])$/, '$1')
}

function windowShare(tokens: number, capacity: number): string {
  if (capacity <= 0) return '—'
  const percent = (tokens / capacity) * 100
  return percent > 0 && percent < 0.1 ? '<0.1%' : `${percent.toFixed(1)}%`
}

function breakdownRows(
  breakdown: ContextBreakdownJson,
  labels: {
    system: string
    tools: string
    mcp: string
    skills: string
    rules: string
    conversation: string
  }
): BreakdownRow[] {
  return [
    {
      key: 'conversation',
      label: labels.conversation,
      tokens: contextBucketTokens(breakdown, 'conversation'),
      color: '#3392ff'
    },
    {
      key: 'tools',
      label: labels.tools,
      tokens: contextBucketTokens(breakdown, 'tool_definitions'),
      color: '#c27bff'
    },
    {
      key: 'mcp',
      label: labels.mcp,
      tokens: contextBucketTokens(breakdown, 'mcp'),
      color: '#fb64b6'
    },
    {
      key: 'skills',
      label: labels.skills,
      tokens: contextBucketTokens(breakdown, 'skills'),
      color: '#fec700'
    },
    {
      key: 'system',
      label: labels.system,
      tokens: contextBucketTokens(breakdown, 'system_prompt'),
      color: '#00d492'
    },
    {
      key: 'rules',
      label: labels.rules,
      tokens: contextBucketTokens(breakdown, 'rules'),
      color: '#00bcff'
    }
  ]
}

export function ContextUsageMeter({
  blocks,
  model,
  hasActiveThread,
  threadId = null,
  busy = false
}: Props): ReactElement {
  const { t } = useTranslation('common')
  const [open, setOpen] = useState(false)
  const [snapshot, setSnapshot] = useState<{
    threadId: string
    model: string
    data: ContextBreakdownJson
  } | null>(null)
  const breakdown =
    hasActiveThread && snapshot?.threadId === threadId && snapshot.model === model
      ? snapshot.data
      : null
  const liveBreakdown = breakdown !== null
  const anchorName = `--context-meter-${useId().replace(/[^a-zA-Z0-9_-]/g, '')}`
  const buttonRef = useRef<HTMLButtonElement | null>(null)
  const panelRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!hasActiveThread || !threadId) {
      setSnapshot(null)
      return
    }
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const fetchBreakdown = async (): Promise<void> => {
      try {
        const r = await window.dsGui.runtimeRequest(
          `/v1/threads/${encodeURIComponent(threadId)}/context`,
          'GET'
        )
        if (!r.ok || cancelled) return
        const data: unknown = JSON.parse(r.body)
        if (isContextBreakdown(data)) {
          setSnapshot({ threadId, model, data })
        }
      } catch {
        // Keep the last reading for this thread during transient failures.
      } finally {
        if (!cancelled && busy) timer = setTimeout(() => void fetchBreakdown(), 2000)
      }
    }
    void fetchBreakdown()
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [hasActiveThread, threadId, blocks.length, model, busy, open])

  const effectiveBreakdown = useMemo(() => {
    if (breakdown) return breakdown
    return fallbackContextBreakdown(blocks, model)
  }, [breakdown, blocks, model])

  const usage = useMemo(() => {
    return snapshotFromContextBreakdown(effectiveBreakdown)
  }, [effectiveBreakdown])

  useLightDismiss({
    open,
    onDismiss: () => setOpen(false),
    refs: [buttonRef, panelRef]
  })

  useEffect(() => {
    setOpen(false)
  }, [threadId])

  const tone =
    usage.level === 'critical'
      ? 'critical'
      : usage.level === 'high'
        ? 'high'
        : 'ok'

  const detailLabel = t('contextUsageLabel', {
    used: formatTokenCount(usage.usedTokens),
    max: formatTokenCount(usage.maxTokens),
    percent: Math.round(usage.percent)
  })

  const rowLabels = {
    system: t('contextBreakdownSystem'),
    tools: t('contextBreakdownTools'),
    mcp: t('contextBreakdownMcp'),
    skills: t('contextBreakdownSkills'),
    rules: t('contextBreakdownRules'),
    conversation: t('contextBreakdownConversation')
  }
  const rows = breakdownRows(effectiveBreakdown, rowLabels)
  const windowTokens = effectiveBreakdown.window
  const barSegments = rows.filter((row) => row.tokens > 0)
  const barUsedTokens = barSegments.reduce((sum, row) => sum + row.tokens, 0)
  const barUsedPct =
    windowTokens > 0 ? Math.min(100, (barUsedTokens / windowTokens) * 100) : 0
  const minimumVisibleBarWidth =
    barSegments.length * USAGE_SEGMENT_MIN_WIDTH +
    Math.max(0, barSegments.length - 1) * USAGE_SEGMENT_GAP

  const panel =
    open
      ? createPortal(
          <div
            ref={panelRef}
            role="dialog"
            aria-label={t('contextBreakdownTitle')}
            className="fixed z-[120] max-h-[calc(100vh-80px)] w-[min(340px,calc(100vw-24px))] overflow-y-auto rounded-[12px] border border-ds-border-muted bg-[var(--ds-surface-elevated)] px-4 py-3 text-[13px] leading-[1.5] text-ds-ink shadow-panel"
            style={{
              positionAnchor: anchorName,
              bottom: 'calc(anchor(top) + 4px)',
              left: 'clamp(12px, calc(anchor(center) - 170px), max(12px, calc(100vw - 352px)))'
            } as CSSProperties}
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className="flex items-center gap-2">
              <div className="flex flex-1 flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                <span className="font-medium">{t('contextBreakdownTitle')}</span>
                <span className="whitespace-nowrap text-[12px] tabular-nums text-ds-muted">
                  {t('contextBreakdownTokenSummary', {
                    used: compactTokens(usage.usedTokens),
                    max: compactTokens(usage.maxTokens)
                  })}{' '}
                  <strong className={`font-semibold ${
                    tone === 'critical' ? 'text-ds-danger' :
                    tone === 'high' ? 'text-amber-600 dark:text-amber-400' : 'text-ds-ink'
                  }`}>
                    ({Math.round(usage.percent)}%)
                  </strong>
                </span>
              </div>
              <button
                type="button"
                aria-label={t('close')}
                className="ds-no-drag -mr-1 flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-ds-faint transition-colors hover:bg-ds-hover hover:text-ds-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
                onClick={() => {
                  setOpen(false)
                  buttonRef.current?.focus()
                }}
              >
                <X aria-hidden="true" className="h-3.5 w-3.5" strokeWidth={1.5} />
              </button>
            </div>

            {/* Preserve real proportions; the small visual floor only prevents bucket clipping. */}
            <div
              aria-hidden="true"
              className="ds-context-usage-bar relative mt-2.5 h-[6px] w-full overflow-hidden rounded-full"
              style={{ backgroundColor: 'color-mix(in srgb, var(--ds-text-faint) 12%, transparent)' }}
            >
              {barSegments.length > 0 && barUsedPct > 0 ? (
                <div
                  className="ds-context-usage-bar__segments absolute inset-y-0 left-0 flex"
                  style={{
                    width: `${barUsedPct}%`,
                    minWidth: `${minimumVisibleBarWidth}px`,
                    gap: `${USAGE_SEGMENT_GAP}px`
                  }}
                >
                  {barSegments.map((row) => (
                    <span
                      key={row.key}
                      className="ds-context-usage-bar__segment"
                      style={{
                        minWidth: `${USAGE_SEGMENT_MIN_WIDTH}px`,
                        flexGrow: row.tokens,
                        flexBasis: 0,
                        backgroundColor: row.color
                      }}
                    />
                  ))}
                </div>
              ) : null}
            </div>

            <ul className="mt-3">
              {rows.map((row) => (
                <li key={row.key} className="grid min-h-8 grid-cols-[10px_minmax(0,1fr)_auto_4em] items-center gap-x-2.5">
                  <span
                    aria-hidden="true"
                    className="h-2.5 w-2.5 shrink-0 rounded-[3px]"
                    style={{ backgroundColor: row.color }}
                  />
                  <span className="min-w-0">{row.label}</span>
                  <span className="text-right text-[13px] tabular-nums text-[color:color-mix(in_srgb,var(--ds-text-muted)_55%,var(--ds-text-faint))]">
                    {compactTokens(row.tokens)}
                  </span>
                  <span className="text-right text-[13px] font-medium tabular-nums">
                    {windowShare(row.tokens, windowTokens)}
                  </span>
                </li>
              ))}
            </ul>

            {!liveBreakdown ? (
              <p className="mt-3 border-t border-ds-border-muted pt-2.5 text-[11px] leading-4 text-ds-muted">
                {t('contextBreakdownEstimateNote')}
              </p>
            ) : null}
          </div>,
          document.body
        )
      : null

  return (
    <div className="relative shrink-0">
      <button
        ref={buttonRef}
        style={{ anchorName } as CSSProperties}
        type="button"
        className={`ds-no-drag flex h-9 w-9 shrink-0 items-center justify-center rounded-full transition ${
          open ? 'text-ds-ink' : 'text-ds-muted hover:text-ds-ink'
        }`}
        aria-label={detailLabel}
        title={detailLabel}
        aria-expanded={open}
        aria-haspopup="dialog"
        onMouseDown={(event) => event.stopPropagation()}
        onClick={(event) => {
          event.stopPropagation()
          setOpen((value) => !value)
        }}
      >
        <UsageRing percent={usage.percent} tone={tone} />
      </button>
      {panel}
    </div>
  )
}

const RING_SIZE = 16
const RING_STROKE = 2
const RING_RADIUS = (RING_SIZE - RING_STROKE) / 2
const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS
const USAGE_SEGMENT_MIN_WIDTH = 2
const USAGE_SEGMENT_GAP = 1
// Solid free-track grey (Cursor-style). Inline color-mix — Tailwind cannot apply
// `/opacity` to `ds-*` CSS-variable colors, so `bg-ds-hover/70` renders as nothing.
const USAGE_TRACK_GREY = 'color-mix(in srgb, var(--ds-text-faint) 42%, transparent)'

function UsageRing({
  percent,
  tone
}: {
  percent: number
  tone: 'ok' | 'high' | 'critical'
}): ReactElement {
  // Keep a visible arc even at very low usage so the meter never looks empty.
  const clamped = Math.max(0, Math.min(100, percent))
  const fillPercent = clamped <= 0 ? 0 : Math.max(clamped, 6)

  const fill =
    tone === 'critical'
      ? 'var(--ds-danger)'
      : tone === 'high'
        ? '#d97706'
        : 'var(--ds-accent)'

  return (
    <svg
      aria-hidden="true"
      width={RING_SIZE}
      height={RING_SIZE}
      viewBox={`0 0 ${RING_SIZE} ${RING_SIZE}`}
      className="shrink-0 -rotate-90"
    >
      <circle
        cx={RING_SIZE / 2}
        cy={RING_SIZE / 2}
        r={RING_RADIUS}
        fill="none"
        stroke={USAGE_TRACK_GREY}
        strokeWidth={RING_STROKE}
      />
      {fillPercent > 0 ? (
        <circle
          cx={RING_SIZE / 2}
          cy={RING_SIZE / 2}
          r={RING_RADIUS}
          fill="none"
          stroke={fill}
          strokeWidth={RING_STROKE}
          strokeLinecap="round"
          strokeDasharray={RING_CIRCUMFERENCE}
          strokeDashoffset={RING_CIRCUMFERENCE * (1 - fillPercent / 100)}
          style={{ transition: 'stroke-dashoffset 200ms ease' }}
        />
      ) : null}
    </svg>
  )
}
