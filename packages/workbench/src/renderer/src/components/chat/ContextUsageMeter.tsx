import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
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
  const [panelStyle, setPanelStyle] = useState<CSSProperties>({})
  const wrapRef = useRef<HTMLDivElement | null>(null)
  const buttonRef = useRef<HTMLButtonElement | null>(null)
  const panelRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!hasActiveThread || !threadId) {
      setBreakdown(null)
      setLiveBreakdown(false)
      return
    }
    let cancelled = false
    void (async () => {
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
    })()
    return () => {
      cancelled = true
    }
  }, [hasActiveThread, threadId, blocks.length, model])

  const effectiveBreakdown = useMemo(() => {
    if (breakdown) return breakdown
    if (hasActiveThread) return fallbackContextBreakdown(blocks, model)
    return null
  }, [breakdown, blocks, model, hasActiveThread])

  const usage = useMemo(() => {
    if (effectiveBreakdown) return snapshotFromContextBreakdown(effectiveBreakdown)
    return null
  }, [effectiveBreakdown])

  const updatePanelPosition = useCallback((): void => {
    const button = buttonRef.current
    if (!button) return
    const rect = button.getBoundingClientRect()
    setPanelStyle({
      position: 'fixed',
      right: Math.max(12, window.innerWidth - rect.right),
      bottom: Math.max(12, window.innerHeight - rect.top + 8),
      zIndex: 120
    })
  }, [])

  useLayoutEffect(() => {
    if (!open) return
    updatePanelPosition()
    window.addEventListener('resize', updatePanelPosition)
    window.addEventListener('scroll', updatePanelPosition, true)
    return () => {
      window.removeEventListener('resize', updatePanelPosition)
      window.removeEventListener('scroll', updatePanelPosition, true)
    }
  }, [open, updatePanelPosition])

  useEffect(() => {
    if (!open) return
    const onPointerDown = (event: PointerEvent): void => {
      const target = event.target
      if (!(target instanceof Node)) return
      if (buttonRef.current?.contains(target)) return
      if (panelRef.current?.contains(target)) return
      setOpen(false)
    }
    const timer = window.setTimeout(() => {
      window.addEventListener('pointerdown', onPointerDown, true)
    }, 0)
    return () => {
      window.clearTimeout(timer)
      window.removeEventListener('pointerdown', onPointerDown, true)
    }
  }, [open])

  useEffect(() => {
    setOpen(false)
  }, [threadId])

  if (!hasActiveThread || !usage || !effectiveBreakdown) {
    return (
      <div
        className="ml-auto flex shrink-0 items-center gap-1.5 text-[12px] text-ds-faint"
        aria-label={t('contextUsageIdle')}
        title={t('contextUsageIdle')}
      >
        <UsageRing percent={0} tone="idle" />
        <span>—</span>
      </div>
    )
  }

  const tone =
    usage.level === 'critical'
      ? 'critical'
      : usage.level === 'high'
        ? 'high'
        : 'ok'

  const percentLabel = `${Math.round(usage.percent)}%`
  const detailLabel = t('contextUsageLabel', {
    used: formatTokenCount(usage.usedTokens),
    max: formatTokenCount(usage.maxTokens),
    percent: Math.round(usage.percent)
  })
  const toneText =
    tone === 'critical'
      ? 'text-rose-600 dark:text-rose-300'
      : tone === 'high'
        ? 'text-amber-700 dark:text-amber-200'
        : 'text-ds-faint'

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

  const panel =
    open && typeof document !== 'undefined'
      ? createPortal(
          <div
            ref={panelRef}
            role="dialog"
            aria-label={t('contextBreakdownTitle')}
            style={panelStyle}
            className="w-[min(520px,calc(100vw-24px))] overflow-hidden rounded-[12px] border border-ds-border bg-ds-elevated px-5 py-4 text-[12px] leading-[1.5] text-ds-muted shadow-[0_24px_70px_rgba(44,55,78,0.18)] backdrop-blur-xl dark:shadow-[0_30px_80px_rgba(0,0,0,0.42)]"
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

            <div className="mt-3.5 flex h-1.5 overflow-hidden rounded-full bg-ds-border-muted">
              {rows.map((row) => {
                const pct = windowTokens > 0 ? (row.tokens / windowTokens) * 100 : 0
                if (pct <= 0) return null
                return (
                  <span
                    key={row.key}
                    className="h-full shrink-0"
                    style={{
                      width: `${Math.max(0.6, pct)}%`,
                      backgroundColor: row.color
                    }}
                  />
                )
              })}
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
          document.body
        )
      : null

  return (
    <div ref={wrapRef} className="relative ml-auto shrink-0">
      <button
        ref={buttonRef}
        type="button"
        className={`flex items-center gap-1.5 text-[12px] font-medium tabular-nums transition hover:text-ds-ink ${toneText} ${
          open ? 'text-ds-ink' : ''
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
        <span>{percentLabel}</span>
      </button>
      {panel}
    </div>
  )
}

const RING_SIZE = 14
const RING_STROKE = 2
const RING_RADIUS = (RING_SIZE - RING_STROKE) / 2
const RING_CIRCUMFERENCE = 2 * Math.PI * RING_RADIUS

function UsageRing({
  percent,
  tone
}: {
  percent: number
  tone: 'idle' | 'ok' | 'high' | 'critical'
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
  const track = 'color-mix(in srgb, var(--ds-text-faint) 28%, transparent)'

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
        stroke={track}
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
