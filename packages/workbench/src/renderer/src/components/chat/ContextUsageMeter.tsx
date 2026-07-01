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
            className="w-[min(520px,calc(100vw-24px))] overflow-hidden rounded-[20px] border border-ds-border bg-ds-elevated px-5 py-4 text-[12px] leading-[1.5] text-ds-muted shadow-[0_24px_70px_rgba(44,55,78,0.18)] backdrop-blur-xl dark:shadow-[0_30px_80px_rgba(0,0,0,0.42)]"
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

            <div className="mt-3.5 flex h-1.5 overflow-hidden rounded-full bg-ds-border-muted/50">
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
