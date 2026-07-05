import { useMemo, type ReactElement } from 'react'
import type { UsageDailyPoint } from '@shared/usage-ledger'
import { formatComposerModelLabel } from '../../lib/composer-model-label'
import type { ComposerModelMeta } from '../../lib/composer-model-label'
import { formatCompactNumber } from '../../hooks/use-model-usage'

const BAR_COLORS = [
  '#5b8def',
  '#3dba8c',
  '#e8a44a',
  '#a78bfa',
  '#38bdf8',
  '#f472b6',
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

function aggregateDailyToBuckets(
  daily: UsageDailyPoint[],
  segmentDays: number
): UsageDailyPoint[] {
  const buckets: UsageDailyPoint[] = []
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
  compact = false,
  showYAxis = false,
  segmentDays
}: Props): ReactElement {
  // When segmented (hero), bucket daily points into N-day bars so every bar is
  // meaningful; otherwise (settings) keep weekly aggregation for long ranges
  // instead of sampling isolated single days and dropping the rest.
  const displayDaily = useMemo(() => {
    if (segmentDays !== undefined) {
      return segmentDays > 1 ? aggregateDailyToBuckets(daily, segmentDays) : daily
    }
    return daily.length > 45 ? aggregateDailyToBuckets(daily, 7) : daily
  }, [daily, segmentDays])
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

  const chartHeight = compact ? 'h-[132px]' : 'h-[112px]'
  // In segmented mode (hero), label every bar when there are few enough; 7d
  // has 7 daily bars and should show all dates. Otherwise cap the tick count.
  const maxDayLabels = segmentDays !== undefined ? 7 : compact ? 5 : 7
  const axisLabelIndices = useMemo(
    () => buildAxisLabelIndices(displayDaily.length, maxDayLabels),
    [displayDaily.length, maxDayLabels]
  )
  const labeledIndices = useMemo(() => new Set(axisLabelIndices), [axisLabelIndices])

  return (
    <div className={compact ? 'space-y-2.5' : 'space-y-3'}>
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
              {yTicks.slice(0, -1).map((tick) => (
                <div key={tick} className="h-px w-full bg-ds-border" />
              ))}
            </div>
          ) : null}
          <div className={['relative flex items-stretch gap-[3px]', chartHeight].join(' ')}>
            {displayDaily.map((point) => {
              const heightPct =
                point.totalTokens > 0 ? Math.max(3, (point.totalTokens / maxTokens) * 100) : 0
              const visibleSegments =
                point.totalTokens <= 0
                  ? []
                  : point.segments.filter((segment) => segment.tokens > 0)
              return (
                <div
                  key={point.day}
                  className="group flex h-full min-w-0 flex-1 flex-col justify-end"
                  title={`${point.label}: ${formatCompactNumber(point.totalTokens)} tokens`}
                >
                  <div
                    className="flex w-full flex-col justify-end overflow-hidden rounded-t-[3px] bg-ds-border"
                    style={{
                      height: point.totalTokens > 0 ? `${heightPct}%` : '2px',
                      minHeight: point.totalTokens > 0 ? '3px' : '2px'
                    }}
                  >
                    {visibleSegments.map((segment, index) => {
                      const isTop = index === visibleSegments.length - 1
                      return (
                        <span
                          key={`${point.day}-${segment.model}`}
                          className={['block w-full shrink-0', isTop ? 'rounded-t-[3px]' : ''].join(' ')}
                          style={{
                            flexGrow: segment.tokens,
                            flexBasis: 0,
                            minHeight: 1,
                            backgroundColor: BAR_COLORS[index % BAR_COLORS.length]
                          }}
                        />
                      )
                    })}
                  </div>
                </div>
              )
            })}
          </div>
          {/*
            Label row mirrors the bar row's flex layout (same gap-1 + flex-1
            tracks), so each label centers exactly on its bar instead of being
            spaced evenly across the whole width. Unlabeled bars keep an empty
            track so the labeled ones stay aligned.
          */}
          <div className="relative mt-1 h-[14px]">
            <div className="flex h-full gap-[3px]">
              {displayDaily.map((point, pointIndex) => {
                if (!labeledIndices.has(pointIndex)) {
                  return <div key={`${point.day}-axis-empty`} className="h-full flex-1" />
                }
                return (
                  <span
                    key={`${point.day}-axis`}
                    className="flex h-full flex-1 items-center justify-center whitespace-nowrap text-[10px] leading-[14px] tabular-nums text-ds-faint"
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
        <div className={compact ? 'flex flex-wrap gap-x-2.5 gap-y-1' : 'flex flex-wrap gap-x-3 gap-y-1.5'}>
          {legendModels.map((model, index) => (
            <span
              key={model}
              className={[
                'inline-flex min-w-0 max-w-full items-center gap-1.5 text-ds-muted',
                compact ? 'text-[10px]' : 'text-[11px]'
              ].join(' ')}
            >
              <span
                className={['shrink-0 rounded-[2px]', compact ? 'h-1.5 w-1.5' : 'h-2 w-2 rounded-full'].join(' ')}
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
