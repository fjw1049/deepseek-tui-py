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
  fallbackContextBreakdown,
  formatBucketPercent,
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
  branch: string
  label: string
  tokens: number
}

function breakdownRows(
  breakdown: ContextBreakdownJson,
  labels: {
    system: string
    tools: string
    conversation: string
    free: string
  }
): BreakdownRow[] {
  return [
    { branch: '├─', label: labels.system, tokens: breakdown.system_prompt },
    { branch: '├─', label: labels.tools, tokens: breakdown.tools },
    { branch: '├─', label: labels.conversation, tokens: breakdown.conversation },
    { branch: '└─', label: labels.free, tokens: breakdown.free }
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
      <div className="ml-auto shrink-0 text-right text-[12px] text-ds-faint">
        {t('contextUsageIdle')}
      </div>
    )
  }

  const tone =
    usage.level === 'critical'
      ? 'text-rose-600 dark:text-rose-300'
      : usage.level === 'high'
        ? 'text-amber-700 dark:text-amber-200'
        : 'text-ds-faint'

  const rowLabels = {
    system: t('contextBreakdownSystem'),
    tools: t('contextBreakdownTools'),
    conversation: t('contextBreakdownConversation'),
    free: t('contextBreakdownFree')
  }
  const rows = breakdownRows(effectiveBreakdown, rowLabels)
  const labelWidth = Math.max(...rows.map((row) => row.label.length))
  const windowTokens = effectiveBreakdown.window

  const panel =
    open && typeof document !== 'undefined'
      ? createPortal(
          <div
            ref={panelRef}
            role="dialog"
            aria-label={t('contextBreakdownTitle')}
            style={panelStyle}
            className="w-[min(320px,calc(100vw-24px))] overflow-hidden rounded-xl border border-ds-border bg-ds-elevated px-3 py-2.5 font-mono text-[11px] leading-[1.45] text-ds-muted shadow-[0_24px_70px_rgba(44,55,78,0.18)] backdrop-blur-xl dark:shadow-[0_30px_80px_rgba(0,0,0,0.42)]"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className="mb-2 text-[12px] font-sans font-medium text-ds-ink">
              {t('contextUsageLabel', {
                used: formatTokenCount(usage.usedTokens),
                max: formatTokenCount(usage.maxTokens),
                percent: Math.round(usage.percent)
              })}
            </div>
            <ul className="space-y-0.5">
              {rows.map((row) => (
                <li key={row.label} className="flex gap-2 whitespace-pre">
                  <span className="shrink-0 text-ds-faint">{row.branch}</span>
                  <span className="shrink-0" style={{ minWidth: `${labelWidth}ch` }}>
                    {row.label}
                  </span>
                  <span className="ml-auto shrink-0 tabular-nums text-ds-ink">
                    {formatTokenCount(row.tokens).padStart(6, ' ')}
                  </span>
                  <span className="shrink-0 tabular-nums text-ds-faint">
                    ({formatBucketPercent(row.tokens, windowTokens)})
                  </span>
                </li>
              ))}
            </ul>
            {!liveBreakdown ? (
              <p className="mt-2 font-sans text-[10.5px] leading-4 text-ds-faint">
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
        className={`text-right text-[12px] font-medium tabular-nums transition hover:text-ds-ink ${tone} ${
          open ? 'text-ds-ink' : ''
        }`}
        aria-expanded={open}
        aria-haspopup="dialog"
        onMouseDown={(event) => event.stopPropagation()}
        onClick={(event) => {
          event.stopPropagation()
          setOpen((value) => !value)
        }}
      >
        {t('contextUsageLabel', {
          used: formatTokenCount(usage.usedTokens),
          max: formatTokenCount(usage.maxTokens),
          percent: Math.round(usage.percent)
        })}
      </button>
      {panel}
    </div>
  )
}
