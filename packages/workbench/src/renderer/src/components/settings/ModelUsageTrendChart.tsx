import { useMemo, type ReactElement } from 'react'
import type { UsageDailyPoint } from '@shared/usage-ledger'
import { formatComposerModelLabel } from '../../lib/composer-model-label'
import type { ComposerModelMeta } from '../../lib/composer-model-label'
import { formatCompactNumber } from '../../hooks/use-model-usage'

const BAR_COLORS = [
  '#6f8cff',
  '#52b788',
  '#f2b56b',
  '#c69bd3',
  '#8b7cf6',
  '#67b7dc',
  '#e07a7a',
  '#7bc8a4',
  '#d4a574',
  '#9b8cff',
  '#5cafff',
  '#f284b6'
]

type Props = {
  daily: UsageDailyPoint[]
  composerModelMeta: Record<string, ComposerModelMeta>
  compact?: boolean
  showYAxis?: boolean
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

function aggregateDailyToWeeks(daily: UsageDailyPoint[]): UsageDailyPoint[] {
  const weeks: UsageDailyPoint[] = []
  // Chunk from the end so the most recent (partial) week aligns to the last day.
  for (let end = daily.length; end > 0; end -= 7) {
    const start = Math.max(0, end - 7)
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
    weeks.unshift({
      day: chunk[0]!.day,
      label: chunk[0]!.label,
      totalTokens,
      segments
    })
  }
  return weeks
}

function axisLabelPosition(
  pointIndex: number,
  totalPoints: number
): { className: string; style?: { left: string } } {
  if (totalPoints <= 1) {
    return { className: 'left-1/2 -translate-x-1/2' }
  }
  if (pointIndex === 0) {
    return { className: 'left-0' }
  }
  if (pointIndex === totalPoints - 1) {
    return { className: 'right-0 text-right' }
  }
  const leftPct = (pointIndex / (totalPoints - 1)) * 100
  return { className: '-translate-x-1/2', style: { left: `${leftPct}%` } }
}

export function ModelUsageTrendChart({
  daily,
  composerModelMeta,
  compact = false,
  showYAxis = false
}: Props): ReactElement {
  // Long ranges (90d) aggregate into weekly bars so every bar is meaningful,
  // instead of sampling isolated single days and dropping the rest.
  const displayDaily = useMemo(
    () => (daily.length > 45 ? aggregateDailyToWeeks(daily) : daily),
    [daily]
  )
  const maxTokens = useMemo(
    () => Math.max(...displayDaily.map((point) => point.totalTokens), 1),
    [displayDaily]
  )
  const yTicks = useMemo(() => {
    if (!showYAxis) return []
    return [maxTokens, maxTokens * 0.75, maxTokens * 0.5, maxTokens * 0.25, 0]
  }, [maxTokens, showYAxis])
  const legendModels = useMemo(() => {
    const seen = new Set<string>()
    const models: string[] = []
    for (const point of daily) {
      for (const segment of point.segments) {
        if (seen.has(segment.model)) continue
        seen.add(segment.model)
        models.push(segment.model)
      }
    }
    return models.slice(0, 6)
  }, [daily])

  const chartHeight = compact ? 'h-[120px]' : 'h-[112px]'
  const maxDayLabels = compact ? 5 : 7
  const axisLabelIndices = useMemo(
    () => buildAxisLabelIndices(displayDaily.length, maxDayLabels),
    [displayDaily.length, maxDayLabels]
  )

  return (
    <div className={compact ? 'space-y-2' : 'space-y-3'}>
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
        <div className="min-w-0 flex-1">
          <div className={['flex items-stretch gap-1', chartHeight].join(' ')}>
            {displayDaily.map((point) => {
              const heightPct =
                point.totalTokens > 0 ? Math.max(12, (point.totalTokens / maxTokens) * 100) : 6
              return (
                <div
                  key={point.day}
                  className="group flex h-full min-w-0 flex-1 flex-col justify-end"
                  title={`${point.label}: ${formatCompactNumber(point.totalTokens)} tokens`}
                >
                  <div
                    className="flex w-full flex-col justify-end overflow-hidden rounded-[4px] bg-ds-border/35"
                    style={{
                      height: `${heightPct}%`,
                      minHeight: point.totalTokens > 0 ? '8px' : '4px'
                    }}
                  >
                    {point.totalTokens <= 0 ? null : (
                      point.segments.map((segment, index) => (
                        <span
                          key={`${point.day}-${segment.model}`}
                          className="block w-full shrink-0"
                          style={{
                            flexGrow: segment.tokens,
                            flexBasis: 0,
                            minHeight: 2,
                            backgroundColor: BAR_COLORS[index % BAR_COLORS.length]
                          }}
                        />
                      ))
                    )}
                  </div>
                </div>
              )
            })}
          </div>
          <div className="relative mt-1 h-[14px]">
            {axisLabelIndices.map((pointIndex) => {
              const point = displayDaily[pointIndex]
              if (!point) return null
              const position = axisLabelPosition(pointIndex, displayDaily.length)
              return (
                <span
                  key={`${point.day}-axis`}
                  className={[
                    'absolute top-0 whitespace-nowrap text-[10px] leading-[14px] tabular-nums text-ds-faint',
                    position.className
                  ].join(' ')}
                  style={position.style}
                >
                  {point.label}
                </span>
              )
            })}
          </div>
        </div>
      </div>
      {legendModels.length > 0 && !compact ? (
        <div className="flex flex-wrap gap-x-3 gap-y-1.5">
          {legendModels.map((model, index) => (
            <span
              key={model}
              className="inline-flex min-w-0 max-w-full items-center gap-1.5 text-[11px] text-ds-muted"
            >
              <span
                className="h-2 w-2 shrink-0 rounded-full"
                style={{ backgroundColor: BAR_COLORS[index % BAR_COLORS.length] }}
              />
              <span className="truncate">{formatComposerModelLabel(model, composerModelMeta)}</span>
            </span>
          ))}
        </div>
      ) : null}
    </div>
  )
}

export { BAR_COLORS as MODEL_USAGE_BAR_COLORS }
