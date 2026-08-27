import {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactElement
} from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import type { ChatBlock } from '../../agent/types'
import {
  contextBucketTokens,
  fallbackContextBreakdown,
  formatTokenCount,
  snapshotFromContextBreakdown,
  type ContextBreakdownJson
} from '../../lib/estimate-context-usage'
import { useLightDismiss } from '../../hooks/use-light-dismiss'

type Props = {
  blocks: ChatBlock[]
  model: string
  hasActiveThread: boolean
  threadId?: string | null
}

type BreakdownRow = {
  key: string
  label: string
  tokens: number
  color: string
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
      key: 'system',
      label: labels.system,
      tokens: contextBucketTokens(breakdown, 'system_prompt'),
      color: '#8b7cf6'
    },
    {
      key: 'tools',
      label: labels.tools,
      tokens: contextBucketTokens(breakdown, 'tool_definitions'),
      color: '#6f8cff'
    },
    {
      key: 'mcp',
      label: labels.mcp,
      tokens: contextBucketTokens(breakdown, 'mcp'),
      color: '#52b788'
    },
    {
      key: 'skills',
      label: labels.skills,
      tokens: contextBucketTokens(breakdown, 'skills'),
      color: '#f2b56b'
    },
    {
      key: 'rules',
      label: labels.rules,
      tokens: contextBucketTokens(breakdown, 'rules'),
      color: '#c69bd3'
    },
    {
      key: 'conversation',
      label: labels.conversation,
      tokens: contextBucketTokens(breakdown, 'conversation'),
      color: '#dc7f68'
    }
  ]
}

export function ContextUsageMeter({
  blocks,
  model,
  hasActiveThread,
  threadId = null
}: Props): ReactElement {
  const { t } = useTranslation('common')
  const [open, setOpen] = useState(false)
  const [breakdown, setBreakdown] = useState<ContextBreakdownJson | null>(null)
  const [liveBreakdown, setLiveBreakdown] = useState(false)
  const [portalHost, setPortalHost] = useState<Element | null>(null)
  const wrapRef = useRef<HTMLDivElement | null>(null)
  const buttonRef = useRef<HTMLButtonElement | null>(null)
  const panelRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!hasActiveThread || !threadId) {
      setBreakdown(null)
      setLiveBreakdown(false)
      return
    }
    setBreakdown(null)
    setLiveBreakdown(false)
    let cancelled = false
    const fetchBreakdown = async (): Promise<void> => {
      try {
        const r = await window.dsGui.runtimeRequest(
          `/v1/threads/${encodeURIComponent(threadId)}/context`,
          'GET'
        )
        if (!r.ok || cancelled) return
        const data = JSON.parse(r.body) as ContextBreakdownJson
        if (!cancelled) {
          setBreakdown(data)
          setLiveBreakdown(true)
        }
      } catch {
        if (!cancelled) {
          setBreakdown(null)
          setLiveBreakdown(false)
        }
      }
    }
    void fetchBreakdown()
    return () => {
      cancelled = true
    }
  }, [hasActiveThread, threadId, blocks.length, model])

  const effectiveBreakdown = useMemo(() => {
    if (breakdown) return breakdown
    return fallbackContextBreakdown(blocks, model)
  }, [breakdown, blocks, model])

  const usage = useMemo(() => {
    return snapshotFromContextBreakdown(effectiveBreakdown)
  }, [effectiveBreakdown])

  useLayoutEffect(() => {
    if (!open) {
      setPortalHost(null)
      return
    }
    const shell = buttonRef.current?.closest('.ds-composer-shell')
    setPortalHost(shell?.parentElement ?? shell ?? document.body)
  }, [open])

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

  const anchoredToComposer = portalHost != null && portalHost !== document.body
  const panel =
    open && portalHost
      ? createPortal(
          <div
            ref={panelRef}
            role="dialog"
            aria-label={t('contextBreakdownTitle')}
            className={`overflow-hidden rounded-[12px] border border-ds-border bg-ds-elevated px-5 py-4 text-[12px] leading-[1.5] text-ds-muted shadow-[0_24px_70px_rgba(44,55,78,0.18)] backdrop-blur-xl dark:shadow-[0_30px_80px_rgba(0,0,0,0.42)] ${
              anchoredToComposer
                ? 'absolute inset-x-0 bottom-full z-[120] mb-1.5 w-full'
                : 'fixed bottom-12 left-3 z-[120] w-[min(520px,calc(100vw-24px))]'
            }`}
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="text-[13px] font-medium tracking-[-0.005em] text-ds-ink">
                  {t('contextBreakdownTitle')}
                </div>
                <div className="mt-1 text-[11.5px] tabular-nums text-ds-faint">
                  {t('contextBreakdownFull', { percent: Math.round(usage.percent) })}
                </div>
              </div>
              <div className="shrink-0 pt-0.5 text-right text-[11.5px] tabular-nums text-ds-faint">
                {t('contextBreakdownTokenSummary', {
                  used: formatTokenCount(usage.usedTokens),
                  max: formatTokenCount(usage.maxTokens)
                })}
              </div>
            </div>

            {/* Cursor-style: solid free-track grey; gaps show it; only outer ends round. */}
            <div
              className="relative mt-3.5 h-[5px] w-full overflow-hidden rounded-full"
              style={{ backgroundColor: USAGE_TRACK_GREY }}
            >
              {barSegments.length > 0 && barUsedPct > 0 ? (
                <div
                  className="absolute inset-y-0 left-0 flex"
                  style={{ width: `${barUsedPct}%`, gap: '1px' }}
                >
                  {barSegments.map((row, index) => {
                    const isFirst = index === 0
                    const isLast = index === barSegments.length - 1
                    const radius =
                      isFirst && isLast
                        ? 'rounded-full'
                        : isFirst
                          ? 'rounded-l-full'
                          : isLast
                            ? 'rounded-r-full'
                            : 'rounded-none'
                    return (
                      <span
                        key={row.key}
                        className={`min-w-[2px] ${radius}`}
                        style={{
                          flexGrow: row.tokens,
                          flexBasis: 0,
                          backgroundColor: row.color
                        }}
                      />
                    )
                  })}
                </div>
              ) : null}
            </div>

            <ul className="mt-3.5 divide-y divide-ds-border-muted/30">
              {rows.map((row) => (
                <li key={row.key} className="flex items-center gap-3 py-2.5">
                  <span
                    className="h-2.5 w-2.5 shrink-0 rounded-[3px]"
                    style={{ backgroundColor: row.color }}
                  />
                  <span className="min-w-0 flex-1 truncate text-ds-muted">
                    {row.label}
                  </span>
                  <span className="shrink-0 tabular-nums text-ds-ink">
                    {formatTokenCount(row.tokens)}
                  </span>
                </li>
              ))}
            </ul>

            {!liveBreakdown ? (
              <p className="mt-3 border-t border-ds-border-muted/40 pt-2.5 text-[10.5px] leading-4 text-ds-faint">
                {t('contextBreakdownEstimateNote')}
              </p>
            ) : null}
          </div>,
          portalHost
        )
      : null

  return (
    <div ref={wrapRef} className="relative shrink-0">
      <button
        ref={buttonRef}
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
