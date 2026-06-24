import { useMemo, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import type { UsageDailyPoint, UsageRange, ModelUsageSummary } from '@shared/usage-ledger'
import { formatComposerModelLabel } from '../../lib/composer-model-label'
import type { ComposerModelMeta } from '../../lib/composer-model-label'
import { formatCompactNumber } from '../../hooks/use-model-usage'
import { MODEL_USAGE_BAR_COLORS, ModelUsageTrendChart } from './ModelUsageTrendChart'

const HEAT_LEVELS = [
  'bg-ds-border/40',
  'bg-accent/20',
  'bg-accent/35',
  'bg-accent/55',
  'bg-accent/75'
]

type HeroTab = 'overview' | 'models'

type Props = {
  summary: ModelUsageSummary | null
  daily: UsageDailyPoint[]
  loading: boolean
  loaded: boolean
  error: string | null
  range: UsageRange
  onRangeChange: (range: UsageRange) => void
  tab: HeroTab
  onTabChange: (tab: HeroTab) => void
  composerModelMeta: Record<string, ComposerModelMeta>
}

function heatLevel(tokens: number, maxTokens: number): number {
  if (tokens <= 0 || maxTokens <= 0) return 0
  const ratio = tokens / maxTokens
  if (ratio >= 0.75) return 4
  if (ratio >= 0.5) return 3
  if (ratio >= 0.25) return 2
  return 1
}

export function ModelUsageHeroPanel({
  summary,
  daily,
  loading,
  loaded,
  error,
  range,
  onRangeChange,
  tab,
  onTabChange,
  composerModelMeta
}: Props): ReactElement {
  const { t } = useTranslation('common')
  const hasUsage = Boolean(summary && summary.totals.totalTokens > 0)
  const activeDays = useMemo(
    () => daily.filter((point) => point.totalTokens > 0).length,
    [daily]
  )
  const topModel = summary?.buckets[0]
  const maxDailyTokens = useMemo(
    () => Math.max(...daily.map((point) => point.totalTokens), 1),
    [daily]
  )
  const visibleModels = summary?.buckets.slice(0, 6) ?? []
  const totalTokens = summary?.totals.totalTokens ?? 0

  const ranges: Array<{ value: UsageRange; labelKey: string }> = [
    { value: '90d', labelKey: 'usageHeroRangeAll' },
    { value: '30d', labelKey: 'usageHeroRange30d' },
    { value: '7d', labelKey: 'usageHeroRange7d' }
  ]

  return (
    <div className="ds-hero-panel ds-glass flex h-full min-h-[420px] flex-col overflow-hidden rounded-[24px] px-4 py-4 sm:px-5 sm:py-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="inline-flex rounded-full border border-ds-border bg-ds-elevated p-0.5">
          {(['overview', 'models'] as const).map((item) => (
            <button
              key={item}
              type="button"
              onClick={() => onTabChange(item)}
              className={[
                'rounded-full px-3 py-1.5 text-[12px] font-medium transition',
                tab === item
                  ? 'bg-ds-card text-ds-ink shadow-sm'
                  : 'text-ds-muted hover:text-ds-ink'
              ].join(' ')}
            >
              {t(item === 'overview' ? 'usageHeroTabOverview' : 'usageHeroTabModels')}
            </button>
          ))}
        </div>
        <div className="inline-flex items-center gap-1 text-[12px]">
          {ranges.map((item) => (
            <button
              key={item.value}
              type="button"
              onClick={() => onRangeChange(item.value)}
              className={[
                'rounded-full px-2.5 py-1 font-medium transition',
                range === item.value
                  ? 'bg-ds-elevated text-ds-ink'
                  : 'text-ds-faint hover:text-ds-muted'
              ].join(' ')}
            >
              {t(item.labelKey)}
            </button>
          ))}
        </div>
      </div>

      {loading && !loaded ? (
        <div className="mt-5 flex-1 animate-pulse rounded-2xl bg-ds-elevated" />
      ) : null}

      {loaded && error ? (
        <p className="mt-5 text-[13px] leading-6 text-ds-muted">{t('usageHeroError')}</p>
      ) : null}

      {loaded && !error && !hasUsage ? (
        <div className="mt-5 flex flex-1 flex-col justify-center rounded-2xl border border-dashed border-ds-border px-4 py-8 text-center">
          <p className="text-[14px] font-medium text-ds-ink">{t('usageHeroTitle')}</p>
          <p className="mt-2 text-[12.5px] leading-6 text-ds-muted">{t('usageHeroEmpty')}</p>
        </div>
      ) : null}

      {loaded && !error && hasUsage && tab === 'overview' ? (
        <div className="mt-4 flex min-h-0 flex-1 flex-col gap-4">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <StatTile label={t('usageHeroStatTokens')} value={formatCompactNumber(totalTokens)} />
            <StatTile
              label={t('usageHeroStatTurns')}
              value={String(summary?.totals.turns ?? 0)}
            />
            <StatTile label={t('usageHeroStatActiveDays')} value={String(activeDays)} />
            <StatTile
              label={t('usageHeroStatTopModel')}
              value={
                topModel
                  ? formatComposerModelLabel(topModel.model, composerModelMeta)
                  : '—'
              }
              truncate
            />
          </div>
          <div className="min-h-0 flex-1 overflow-hidden rounded-2xl border border-ds-border/70 bg-ds-card/50 px-3 py-3">
            <p className="mb-2 text-[11px] font-medium uppercase tracking-[0.08em] text-ds-faint">
              {t('usageHeroActivity')}
            </p>
            <div className="ds-usage-heatmap-scroll overflow-x-auto pb-1">
              <div className="inline-grid grid-flow-col grid-rows-7 gap-[3px]">
                {daily.map((point) => {
                  const level = heatLevel(point.totalTokens, maxDailyTokens)
                  return (
                    <span
                      key={point.day}
                      title={`${point.label}: ${formatCompactNumber(point.totalTokens)} tokens`}
                      className={[
                        'h-[11px] w-[11px] rounded-[3px]',
                        HEAT_LEVELS[level]
                      ].join(' ')}
                    />
                  )
                })}
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {loaded && !error && hasUsage && tab === 'models' ? (
        <div className="mt-4 flex min-h-0 flex-1 flex-col gap-3">
          <div className="rounded-2xl border border-ds-border/70 bg-ds-card/50 px-3 py-3">
            <ModelUsageTrendChart
              daily={daily}
              composerModelMeta={composerModelMeta}
              compact
              showYAxis
            />
          </div>
          <div className="min-h-0 flex-1 space-y-1 overflow-y-auto pr-1">
            {visibleModels.map((bucket, index) => {
              const share =
                totalTokens > 0
                  ? ((bucket.totalTokens / totalTokens) * 100).toFixed(1)
                  : '0.0'
              const label = formatComposerModelLabel(bucket.model, composerModelMeta)
              return (
                <div
                  key={bucket.model}
                  className="flex items-center gap-2 rounded-xl px-2 py-2 text-[12.5px] hover:bg-ds-elevated/70"
                >
                  <span
                    className="h-2.5 w-2.5 shrink-0 rounded-[3px]"
                    style={{ backgroundColor: MODEL_USAGE_BAR_COLORS[index % MODEL_USAGE_BAR_COLORS.length] }}
                  />
                  <span className="min-w-0 flex-1 truncate font-medium text-ds-ink" title={label}>
                    {label}
                  </span>
                  <span className="hidden shrink-0 tabular-nums text-ds-faint sm:inline">
                    {formatCompactNumber(bucket.inputTokens)} in ·{' '}
                    {formatCompactNumber(bucket.outputTokens)} out
                  </span>
                  <span className="w-12 shrink-0 text-right tabular-nums text-ds-muted">
                    {share}%
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      ) : null}
    </div>
  )
}

function StatTile({
  label,
  value,
  truncate = false
}: {
  label: string
  value: string
  truncate?: boolean
}): ReactElement {
  return (
    <div className="rounded-2xl border border-ds-border/70 bg-ds-card/55 px-3 py-2.5">
      <p className="text-[10.5px] font-medium uppercase tracking-[0.06em] text-ds-faint">{label}</p>
      <p
        className={[
          'mt-1 text-[15px] font-semibold tabular-nums text-ds-ink',
          truncate ? 'truncate' : ''
        ].join(' ')}
        title={truncate ? value : undefined}
      >
        {value}
      </p>
    </div>
  )
}
