import { useMemo, type ReactElement } from 'react'
import type { UsageDailyPoint } from '@shared/usage-ledger'
import { formatComposerModelLabel } from '../../lib/composer-model-label'
import type { ComposerModelMeta } from '../../lib/composer-model-label'
import { formatCompactNumber } from '../../hooks/use-model-usage'

const BAR_COLORS = ['#6f8cff', '#52b788', '#f2b56b', '#c69bd3', '#8b7cf6', '#67b7dc']

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

export function ModelUsageTrendChart({
  daily,
  composerModelMeta,
  compact = false,
  showYAxis = false
}: Props): ReactElement {
  const maxTokens = useMemo(
    () => Math.max(...daily.map((point) => point.totalTokens), 1),
    [daily]
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

  return (
    <div className={compact ? 'space-y-2.5' : 'space-y-3'}>
      <div className="flex gap-2">
        {showYAxis ? (
          <div className={`flex ${chartHeight} w-9 shrink-0 flex-col justify-between py-0.5 text-right`}>
            {yTicks.map((tick) => (
              <span key={tick} className="text-[10px] tabular-nums text-ds-faint">
                {formatAxisLabel(tick)}
              </span>
            ))}
          </div>
        ) : null}
        <div className={['flex min-w-0 flex-1 items-end gap-1', chartHeight].join(' ')}>
          {daily.map((point, pointIndex) => {
            const heightPct =
              point.totalTokens > 0 ? Math.max(8, (point.totalTokens / maxTokens) * 100) : 4
            const showLabel =
              !compact ||
              pointIndex === 0 ||
              pointIndex === daily.length - 1 ||
              pointIndex % Math.ceil(daily.length / 5) === 0
            return (
              <div
                key={point.day}
                className="group flex min-w-0 flex-1 flex-col items-center justify-end"
                title={`${point.label}: ${formatCompactNumber(point.totalTokens)} tokens`}
              >
                <div
                  className="flex w-full flex-col justify-end overflow-hidden rounded-[4px] bg-ds-border/35"
                  style={{
                    height: `${heightPct}%`,
                    minHeight: point.totalTokens > 0 ? '6px' : '3px'
                  }}
                >
                  {point.segments.map((segment, index) => {
                    const share = point.totalTokens > 0 ? segment.tokens / point.totalTokens : 0
                    return (
                      <span
                        key={`${point.day}-${segment.model}`}
                        className="block w-full"
                        style={{
                          height: `${Math.max(share * 100, 0)}%`,
                          minHeight: segment.tokens > 0 ? '1px' : 0,
                          backgroundColor: BAR_COLORS[index % BAR_COLORS.length]
                        }}
                      />
                    )
                  })}
                </div>
                {showLabel ? (
                  <span className="mt-1 truncate text-center text-[10px] tabular-nums text-ds-faint">
                    {point.label}
                  </span>
                ) : (
                  <span className="mt-1 h-[14px]" aria-hidden />
                )}
              </div>
            )
          })}
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
