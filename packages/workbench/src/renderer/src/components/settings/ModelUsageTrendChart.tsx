import { useEffect, useId, useMemo, useState, type ReactElement } from 'react'
import type { UsageDailyPoint } from '@shared/usage-ledger'
import { formatComposerModelLabel } from '../../lib/composer-model-label'
import type { ComposerModelMeta } from '../../lib/composer-model-label'
import { formatCompactNumber } from '../../hooks/use-model-usage'

const SELECTED_POINT_TIMEOUT_MS = 3000
const ACTIVE_PURPLE_COLORS = ['#bd73ff', '#a058e8', '#8746ce', '#7132b1', '#cc94ff', '#aa6fda']

const BAR_COLORS = [
  '#2979ff',
  '#ff7100',
  '#00b69e',
  '#854dff',
  '#00a5dd',
  '#e43887',
  '#84cc16',
  '#fb7185',
  '#22d3ee',
  '#fbbf24',
  '#818cf8',
  '#34d399'
]

type Props = {
  daily: UsageDailyPoint[]
  composerModelMeta: Record<string, ComposerModelMeta>
  modelOrder?: string[]
  variant?: 'bar' | 'line'
  colorScheme?: 'models' | 'purple'
  compact?: boolean
  showYAxis?: boolean
  /**
   * Group daily points into N-day bars and align each bar's axis label to its
   * center. Pass 1 for daily bars (no bucketing). When unset, the chart keeps
   * its default behavior (weekly bars for ranges over 45 days, otherwise
   * daily bars with evenly distributed axis labels).
   */
  segmentDays?: number
}

function formatAxisLabel(tokens: number): string {
  if (tokens >= 1_000_000) return `${(tokens / 1_000_000).toFixed(1)}M`
  if (tokens >= 1_000) return `${(tokens / 1_000).toFixed(1)}k`
  return String(tokens)
}

function buildAxisLabelIndices(totalPoints: number, maxLabels: number): number[] {
  if (totalPoints <= 0) return []
  if (totalPoints <= maxLabels) {
    return Array.from({ length: totalPoints }, (_, index) => index)
  }
  // Evenly distribute ticks including first and last so gaps stay uniform —
  // a ceil-based step leaves an uneven (cramped) final gap.
  const ticks = Math.max(2, maxLabels)
  const indices = new Set<number>()
  for (let i = 0; i < ticks; i += 1) {
    indices.add(Math.round((i * (totalPoints - 1)) / (ticks - 1)))
  }
  return Array.from(indices).sort((a, b) => a - b)
}

type ChartPoint = UsageDailyPoint & { endDay?: string }

function aggregateDailyToBuckets(
  daily: UsageDailyPoint[],
  segmentDays: number
): ChartPoint[] {
  const buckets: ChartPoint[] = []
  // Chunk from the end so the most recent (partial) bucket aligns to the last day.
  for (let end = daily.length; end > 0; end -= segmentDays) {
    const start = Math.max(0, end - segmentDays)
    const chunk = daily.slice(start, end)
    const tokensByModel = new Map<string, number>()
    let totalTokens = 0
    for (const point of chunk) {
      totalTokens += point.totalTokens
      for (const segment of point.segments) {
        tokensByModel.set(segment.model, (tokensByModel.get(segment.model) ?? 0) + segment.tokens)
      }
    }
    const segments = Array.from(tokensByModel, ([model, tokens]) => ({ model, tokens })).sort(
      (a, b) => b.tokens - a.tokens || a.model.localeCompare(b.model)
    )
    buckets.unshift({
      day: chunk[0]!.day,
      endDay: chunk[chunk.length - 1]!.day,
      label: chunk[0]!.label,
      totalTokens,
      segments
    })
  }
  return buckets
}

export function ModelUsageTrendChart({
  daily,
  composerModelMeta,
  modelOrder,
  variant = 'bar',
  colorScheme = 'models',
  compact = false,
  showYAxis = false,
  segmentDays
}: Props): ReactElement {
  const gradientId = useId()
  const detailId = useId()
  const [selection, setSelection] = useState<string | null>(null)
  useEffect(() => {
    if (!selection) return
    const timer = window.setTimeout(() => setSelection(null), SELECTED_POINT_TIMEOUT_MS)
    return () => window.clearTimeout(timer)
  }, [selection])
  const rangeKey = `${daily[0]?.day}:${daily[daily.length - 1]?.day}:${segmentDays}`
  // When segmented (hero), bucket daily points into N-day bars so every bar is
  // meaningful; otherwise (settings) keep weekly aggregation for long ranges
  // instead of sampling isolated single days and dropping the rest.
  const displayDaily = useMemo<ChartPoint[]>(() => {
    if (segmentDays !== undefined) {
      return segmentDays > 1 ? aggregateDailyToBuckets(daily, segmentDays) : daily
    }
    return daily.length > 45 ? aggregateDailyToBuckets(daily, 7) : daily
  }, [daily, segmentDays])
  const legendModels = useMemo(() => {
    const models = new Set(modelOrder)
    for (const point of daily) {
      for (const segment of point.segments) models.add(segment.model)
    }
    return Array.from(models)
  }, [daily, modelOrder])
  const [hidden, setHidden] = useState<Set<string>>(() => new Set())
  const filteredDaily = useMemo(() => displayDaily.map(point => {
    const segments = point.segments.filter(segment => !hidden.has(segment.model))
      .sort((a, b) => legendModels.indexOf(a.model) - legendModels.indexOf(b.model))
    return { ...point, segments, totalTokens: segments.reduce((sum, segment) => sum + segment.tokens, 0) }
  }), [displayDaily, hidden, legendModels])
  const selectedPoint = filteredDaily.find(point => selection === `${rangeKey}:${point.day}`)
  const maxTokens = useMemo(
    () => Math.max(...filteredDaily.map((point) => point.totalTokens), 1),
    [filteredDaily]
  )
  const yTicks = useMemo(() => {
    if (!showYAxis) return []
    return [maxTokens, maxTokens * 0.75, maxTokens * 0.5, maxTokens * 0.25, 0]
  }, [maxTokens, showYAxis])
  const colors = colorScheme === 'purple'
    ? ['#c79aff', '#a879ed', '#8d5cce', '#7547b0', '#ddbaff', '#b187df']
    : BAR_COLORS
  const linePoints = filteredDaily.map((point, index) => ({
    x: ((index + 0.5) / filteredDaily.length) * 100,
    y: 98 - (point.totalTokens / maxTokens) * 94
  }))
  const selectedLinePoint = selectedPoint
    ? linePoints[filteredDaily.indexOf(selectedPoint)]
    : undefined
  const linePath = linePoints.map((point, index) =>
    `${index === 0 ? 'M' : 'L'} ${point.x} ${point.y}`
  ).join(' ')
  // Only consecutive zero-value points form an idle span. Keep the ramps
  // into/out of real usage purple, and keep each dashed span continuous.
  const lineStrokes: { idle: boolean; path: string }[] = []
  for (let index = 1; index < linePoints.length; index += 1) {
    const previous = linePoints[index - 1]!
    const point = linePoints[index]!
    const idle = filteredDaily[index - 1]!.totalTokens === 0 && filteredDaily[index]!.totalTokens === 0
    const last = lineStrokes[lineStrokes.length - 1]
    if (last?.idle === idle) last.path += ` L ${point.x} ${point.y}`
    else lineStrokes.push({ idle, path: `M ${previous.x} ${previous.y} L ${point.x} ${point.y}` })
  }
  const chartHeight = compact ? 'h-[132px]' : 'h-[200px]'
  // In segmented mode (hero), label every bar when there are few enough; 7d
  // has 7 daily bars and should show all dates. Otherwise cap the tick count.
  const maxDayLabels = segmentDays !== undefined ? 7 : compact ? 5 : 7
  const axisLabelIndices = useMemo(
    () => buildAxisLabelIndices(displayDaily.length, maxDayLabels),
    [displayDaily.length, maxDayLabels]
  )
  const labeledIndices = useMemo(() => new Set(axisLabelIndices), [axisLabelIndices])

  return (
    <div className="space-y-2.5" onKeyDown={(event) => {
      if (event.key === 'Escape') setSelection(null)
    }}>
      <div className="flex gap-2">
        {showYAxis ? (
          <div
            className={`flex w-9 shrink-0 flex-col justify-between py-0.5 text-right ${chartHeight}`}
          >
            {yTicks.map((tick) => (
              <span key={tick} className="text-[10px] leading-none tabular-nums text-ds-faint">
                {formatAxisLabel(tick)}
              </span>
            ))}
          </div>
        ) : null}
        <div className="relative min-w-0 flex-1">
          {showYAxis ? (
            <div
              className={['pointer-events-none absolute inset-x-0 top-0 flex flex-col justify-between', chartHeight].join(
                ' '
              )}
              aria-hidden
            >
              {yTicks.map((tick) => (
                <div key={tick} className="w-full border-t border-dashed border-ds-border-muted" />
              ))}
            </div>
          ) : null}
          <div className={['relative flex items-stretch', chartHeight].join(' ')} style={{ gap: `min(5px, ${20 / Math.max(displayDaily.length, 1)}%)` }}>
            {variant === 'line' && linePoints.length > 0 ? (
              <svg aria-hidden="true" viewBox="0 0 100 100" preserveAspectRatio="none" className="pointer-events-none absolute inset-0 h-full w-full text-accent" style={colorScheme === 'purple' ? { color: '#b77bfa' } : undefined}>
                <defs>
                  <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="currentColor" stopOpacity="0.32" />
                    <stop offset="100%" stopColor="currentColor" stopOpacity="0" />
                  </linearGradient>
                </defs>
                <path d={`${linePath} L ${linePoints[linePoints.length - 1]!.x} 98 L ${linePoints[0]!.x} 98 Z`} fill={`url(#${gradientId})`} />
                {lineStrokes.map((segment, index) => (
                  <path key={index} data-usage-stroke={segment.idle ? 'idle' : 'active'}
                    d={segment.path} fill="none" stroke="currentColor" strokeWidth="1.5"
                    className={segment.idle ? 'text-ds-faint' : undefined}
                    strokeDasharray={segment.idle ? '4 4' : undefined}
                    vectorEffect="non-scaling-stroke" />
                ))}
                {linePoints.length === 1 ? <path
                  data-usage-stroke={filteredDaily[0]!.totalTokens === 0 ? 'idle' : 'active'}
                  className={filteredDaily[0]!.totalTokens === 0 ? 'text-ds-faint' : undefined}
                  d={`M ${linePoints[0]!.x - 0.4} ${linePoints[0]!.y} h 0.8`}
                  stroke="currentColor" strokeWidth="3" strokeLinecap="round" vectorEffect="non-scaling-stroke" /> : null}
              </svg>
            ) : null}
            {variant === 'line' && selectedLinePoint ? (
              <div aria-hidden="true" data-chart-selection="line" className="pointer-events-none absolute inset-0 z-10">
                <span
                  className="absolute bottom-[2%] top-0 border-l border-dashed border-ds-faint opacity-40"
                  style={{ left: `${selectedLinePoint.x}%` }}
                />
                <span
                  className={`absolute h-5 w-5 -translate-x-1/2 -translate-y-1/2 rounded-full border-[3px] bg-ds-subtle ${selectedPoint?.totalTokens === 0 ? 'border-ds-border-muted' : 'border-[#c79aff]/40'}`}
                  style={{ left: `${selectedLinePoint.x}%`, top: `${selectedLinePoint.y}%` }}
                >
                  <span className={`absolute inset-[3px] rounded-full ${selectedPoint?.totalTokens === 0 ? 'bg-ds-faint' : 'bg-[#b344ff]'}`} />
                </span>
              </div>
            ) : null}
            {filteredDaily.map((point) => {
              const heightPct =
                point.totalTokens > 0 ? Math.max(3, (point.totalTokens / maxTokens) * 100) : 0
              const visibleSegments =
                point.totalTokens <= 0
                  ? []
                  : point.segments.filter((segment) => segment.tokens > 0)
              return (
                <button
                  type="button"
                  key={point.day}
                  className="group relative flex h-full min-w-0 flex-1 cursor-pointer flex-col justify-end border-0 bg-transparent p-0 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
                  tabIndex={0}
                  aria-expanded={selectedPoint?.day === point.day}
                  aria-controls={selectedPoint?.day === point.day ? detailId : undefined}
                  onClick={() => setSelection(current => current === `${rangeKey}:${point.day}` ? null : `${rangeKey}:${point.day}`)}
                  aria-label={`${point.day}${point.endDay && point.endDay !== point.day ? ` – ${point.endDay}` : ''}: ${point.totalTokens.toLocaleString()} tokens`}
                  title={`${point.label}: ${formatCompactNumber(point.totalTokens)} tokens`}
                >
                  <span
                    className={`flex w-full flex-col-reverse overflow-hidden ${point.totalTokens > 0 ? 'rounded-t-[3px] bg-ds-border' : 'rounded-full bg-ds-border-muted'}`}
                    style={{
                      opacity: variant === 'line' ? 0 : 1,
                      height: point.totalTokens > 0 ? `${heightPct}%` : '4px',
                      minHeight: point.totalTokens > 0 ? '3px' : '4px'
                    }}
                  >
                    {visibleSegments.map((segment) => (
                      <span
                        key={`${point.day}-${segment.model}`}
                        className="block w-full shrink-0"
                        style={{
                          flexGrow: segment.tokens,
                          flexBasis: 0,
                          minHeight: 1,
                          backgroundColor: variant === 'bar' && colorScheme === 'purple' && selectedPoint?.day === point.day
                            ? ACTIVE_PURPLE_COLORS[legendModels.indexOf(segment.model) % ACTIVE_PURPLE_COLORS.length]
                            : colors[legendModels.indexOf(segment.model) % colors.length]
                        }}
                      />
                    ))}
                  </span>
                </button>
              )
            })}
          </div>
          {selectedPoint ? (
            <div id={detailId} role="status" className="absolute top-2 z-20 overflow-y-auto rounded-xl border border-ds-border-muted bg-ds-elevated p-3 text-xs text-ds-muted shadow-lg"
              style={{
                ...(selectedLinePoint && selectedLinePoint.x < 50 ? { right: 8 } : { left: 8 }),
                width: 'min(280px, calc(50% - 12px))',
                maxHeight: compact ? 108 : 176
              }}>
              <div className="flex flex-col gap-1">
                <span>{selectedPoint.day}{selectedPoint.endDay && selectedPoint.endDay !== selectedPoint.day ? ` – ${selectedPoint.endDay}` : ''}</span>
                <strong className="font-medium tabular-nums text-ds-ink">{selectedPoint.totalTokens.toLocaleString()} tokens</strong>
              </div>
              <dl className="mt-2 space-y-1">
                {selectedPoint.segments.filter(segment => segment.tokens > 0).map(segment => (
                  <div key={segment.model} className="flex items-baseline justify-between gap-3">
                    <dt className="min-w-0 break-all">
                      <span aria-hidden="true" className="mr-1.5 inline-block h-1.5 w-1.5 rounded-full" style={{ backgroundColor: colors[legendModels.indexOf(segment.model) % colors.length] }} />
                      {formatComposerModelLabel(segment.model, composerModelMeta)}
                    </dt>
                    <dd className="shrink-0 tabular-nums">{segment.tokens.toLocaleString()}</dd>
                  </div>
                ))}
              </dl>
            </div>
          ) : null}
          {/*
            Label row mirrors the bar row's flex layout (same gap-1 + flex-1
            tracks), so each label centers exactly on its bar instead of being
            spaced evenly across the whole width. Unlabeled bars keep an empty
            track so the labeled ones stay aligned.
          */}
          <div className="relative mt-1 h-[14px]">
            <div className="flex h-full" style={{ gap: `min(5px, ${20 / Math.max(displayDaily.length, 1)}%)` }}>
              {displayDaily.map((point, pointIndex) => {
                if (!labeledIndices.has(pointIndex)) {
                  return <div key={`${point.day}-axis-empty`} className="h-full min-w-0 flex-1" />
                }
                return (
                  <span
                    key={`${point.day}-axis`}
                    className={`flex h-full min-w-0 flex-1 items-center whitespace-nowrap text-[10px] leading-[14px] tabular-nums text-ds-faint ${pointIndex === 0 ? 'justify-start' : pointIndex === displayDaily.length - 1 ? 'justify-end' : 'justify-center'}`}
                  >
                    {point.label}
                  </span>
                )
              })}
            </div>
          </div>
        </div>
      </div>
      {legendModels.length > 0 ? (
        <div className="flex flex-wrap gap-x-3 gap-y-1 pt-1">
          {legendModels.map((model, index) => (
            <button
              type="button"
              aria-pressed={!hidden.has(model)}
              onClick={() => setHidden(current => {
                const next = new Set(current)
                if (next.has(model)) next.delete(model)
                else next.add(model)
                return next
              })}
              key={model}
              className="inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-md px-1 py-1 text-[10px] leading-tight text-ds-muted opacity-50 hover:bg-ds-elevated focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent aria-pressed:opacity-100"
            >
              <span
                className="h-1.5 w-1.5 shrink-0 rounded-full"
                style={{ backgroundColor: colors[index % colors.length] }}
              />
              <span className="truncate">{formatComposerModelLabel(model, composerModelMeta)}</span>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  )
}

export { BAR_COLORS as MODEL_USAGE_BAR_COLORS }
