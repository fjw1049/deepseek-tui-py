import { useMemo, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { BarChart3 } from 'lucide-react'
import type { UsageDailyPoint, UsageRange } from '@shared/usage-ledger'
import { formatComposerModelLabel } from '../../lib/composer-model-label'
import type { ComposerModelMeta } from '../../lib/composer-model-label'
import {
  formatCompactNumber,
  formatCost,
  type ModelUsageSummary
} from '../../hooks/use-model-usage'
import { ModelUsageTrendChart } from './ModelUsageTrendChart'

const BAR_COLORS = ['#6f8cff', '#52b788', '#f2b56b', '#c69bd3', '#8b7cf6', '#67b7dc']
const RANGES: Array<{ value: UsageRange; labelKey: string }> = [
  { value: '7d', labelKey: 'modelUsageRange7d' },
  { value: '30d', labelKey: 'modelUsageRange30d' },
  { value: '90d', labelKey: 'modelUsageRange90d' }
]

type Props = {
  usage: ModelUsageSummary | null
  daily: UsageDailyPoint[]
  loading: boolean
  loaded: boolean
  error: string | null
  activeModelId?: string
  composerModelMeta: Record<string, ComposerModelMeta>
  range: UsageRange
  onRangeChange: (range: UsageRange) => void
}

export function ModelUsagePanel({
  usage,
  daily,
  loading,
  loaded,
  error,
  activeModelId = '',
  composerModelMeta,
  range,
  onRangeChange
}: Props): ReactElement {
  const { t, i18n } = useTranslation('settings')
  const buckets = usage?.buckets ?? []
  const maxTokens = useMemo(
    () => Math.max(...buckets.map((bucket) => bucket.totalTokens), 1),
    [buckets]
  )

  return (
    <div className="px-4 py-5">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-ds-subtle text-ds-muted">
            <BarChart3 className="h-4 w-4" strokeWidth={1.85} />
          </div>
          <div className="min-w-0">
            <h3 className="text-[14px] font-semibold text-ds-ink">{t('modelUsageTitle')}</h3>
            <p className="mt-1 text-[13px] leading-6 text-ds-muted">{t('modelUsageDesc')}</p>
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-3">
          <div className="inline-flex rounded-full border border-ds-border bg-ds-elevated p-1">
            {RANGES.map((item) => (
              <button
                key={item.value}
                type="button"
                onClick={() => onRangeChange(item.value)}
                className={[
                  'rounded-full px-2.5 py-1 text-[11.5px] font-medium transition',
                  range === item.value
                    ? 'bg-accent text-white shadow-sm'
                    : 'text-ds-muted hover:text-ds-ink'
                ].join(' ')}
              >
                {t(item.labelKey)}
              </button>
            ))}
          </div>
          {usage ? (
            <div className="text-right text-[12px] tabular-nums text-ds-muted">
              <div>{t('modelUsageTotalTokens', { tokens: formatCompactNumber(usage.totals.totalTokens) })}</div>
              <div className="mt-0.5">
                {t('modelUsageTotalCost', {
                  cost: formatCost(usage.totals.costUsd, i18n.language, usage.totals.costCny)
                })}
              </div>
            </div>
          ) : null}
        </div>
      </div>

      {loading && !loaded ? (
        <p className="mt-4 text-[13px] text-ds-faint">{t('modelUsageLoading')}</p>
      ) : null}

      {error ? (
        <p className="mt-4 rounded-xl border border-red-300/70 bg-red-50/80 px-4 py-5 text-[13px] leading-6 text-red-800 dark:border-red-800/50 dark:bg-red-950/30 dark:text-red-100">
          {t('modelUsageError', { message: error })}
        </p>
      ) : null}

      {!error && !loading && loaded && (!usage || buckets.length === 0) ? (
        <p className="mt-4 rounded-xl border border-dashed border-ds-border px-4 py-5 text-[13px] leading-6 text-ds-muted">
          {t('modelUsageEmpty')}
        </p>
      ) : null}

      {!error && usage && buckets.length > 0 ? (
        <>
          <div className="mt-4 rounded-xl border border-ds-border-muted bg-ds-card/60 px-3 py-3">
            <ModelUsageTrendChart
              daily={daily}
              composerModelMeta={composerModelMeta}
              showYAxis
            />
          </div>
          <div className="mt-4 max-h-[min(420px,50vh)] space-y-3 overflow-y-auto pb-3 pr-1">
          {buckets.map((bucket, index) => {
            const label = formatComposerModelLabel(bucket.model, composerModelMeta)
            const widthPct = Math.max(4, (bucket.totalTokens / maxTokens) * 100)
            const active =
              activeModelId.trim() !== '' &&
              (bucket.model === activeModelId.trim() ||
                formatComposerModelLabel(bucket.model, composerModelMeta) ===
                  formatComposerModelLabel(activeModelId, composerModelMeta))
            const color = BAR_COLORS[index % BAR_COLORS.length]
            return (
              <div
                key={bucket.model}
                className={`rounded-xl border px-3 py-2.5 ${
                  active
                    ? 'border-accent/35 bg-accent/5'
                    : 'border-ds-border-muted bg-ds-card/60'
                }`}
              >
                <div className="flex items-center justify-between gap-3">
                  <span
                    className={`min-w-0 truncate text-[13px] font-medium ${
                      active ? 'text-ds-ink' : 'text-ds-muted'
                    }`}
                    title={label}
                  >
                    {label}
                  </span>
                  <span className="shrink-0 text-[12px] tabular-nums text-ds-muted">
                    {formatCompactNumber(bucket.totalTokens)} tokens
                  </span>
                </div>
                <div className="mt-2 h-2 overflow-hidden rounded-full bg-ds-border/70">
                  <span
                    className="block h-full rounded-full"
                    style={{ width: `${widthPct}%`, backgroundColor: color }}
                  />
                </div>
                <div className="mt-1.5 flex flex-wrap items-center gap-x-2 text-[11.5px] tabular-nums text-ds-faint">
                  <span>
                    {t('modelUsageInOut', {
                      input: formatCompactNumber(bucket.inputTokens),
                      output: formatCompactNumber(bucket.outputTokens)
                    })}
                  </span>
                  {(bucket.costUsd ?? 0) > 0 || (bucket.costCny ?? 0) > 0 ? (
                    <>
                      <span>·</span>
                      <span>
                        {formatCost(bucket.costUsd, i18n.language, bucket.costCny)}
                      </span>
                    </>
                  ) : null}
                  {bucket.turns > 0 ? (
                    <>
                      <span>·</span>
                      <span>{t('modelUsageTurns', { turns: bucket.turns })}</span>
                    </>
                  ) : null}
                </div>
              </div>
            )
          })}
          </div>
        </>
      ) : null}
    </div>
  )
}
