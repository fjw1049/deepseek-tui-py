import { useMemo, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import type { UsageDailyPoint, UsageRange, ModelUsageSummary } from '@shared/usage-ledger'
import {
  formatComposerModelLabel,
  formatUsageModelName
} from '../../lib/composer-model-label'
import type { ComposerModelMeta } from '../../lib/composer-model-label'
import { formatCompactNumber } from '../../hooks/use-model-usage'
import { MODEL_USAGE_BAR_COLORS, ModelUsageTrendChart } from './ModelUsageTrendChart'
import { UsageActivityHeatmap } from './UsageActivityHeatmap'
import { GlassSegmentedControl } from './GlassSegmentedControl'

type HeroTab = 'overview' | 'models'

type Props = {
  summary: ModelUsageSummary | null
  daily: UsageDailyPoint[]
  heatmapDaily: UsageDailyPoint[]
  heatmapAsOfDay?: string
  loading: boolean
  loaded: boolean
  error: string | null
  range: UsageRange
  onRangeChange: (range: UsageRange) => void
  tab: HeroTab
  onTabChange: (tab: HeroTab) => void
  composerModelMeta: Record<string, ComposerModelMeta>
}

export function ModelUsageHeroPanel({
  summary,
  daily,
  heatmapDaily,
  heatmapAsOfDay,
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
  const topModelName = topModel
    ? formatUsageModelName(topModel.model, composerModelMeta)
    : '—'
  const modelBuckets = summary?.buckets ?? []
  const totalTokens = summary?.totals.totalTokens ?? 0

  const ranges: Array<{ value: UsageRange; labelKey: string }> = [
    { value: '90d', labelKey: 'usageHeroRangeAll' },
    { value: '30d', labelKey: 'usageHeroRange30d' },
    { value: '7d', labelKey: 'usageHeroRange7d' }
  ]

  // Segment the trend chart by range: 7d shows every day, 30d groups into
  // 2-day bars, 90d groups into 3-day bars.
  const segmentDays = range === '7d' ? 1 : range === '30d' ? 2 : 3

  return (
    <div className="ds-hero-panel ds-glass ds-content-card--interactive ds-empty-hero-panel flex flex-col overflow-hidden rounded-[22px] px-4 py-4 sm:px-5 sm:py-5">
      <div className="flex shrink-0 flex-nowrap items-center justify-between gap-3">
        <GlassSegmentedControl
          value={tab}
          onChange={onTabChange}
          items={[
            { value: 'overview', label: t('usageHeroTabOverview') },
            { value: 'models', label: t('usageHeroTabModels') }
          ]}
        />
        <GlassSegmentedControl
          value={range}
          onChange={onRangeChange}
          segmentClassName="px-2.5 py-1.5"
          items={ranges.map((item) => ({
            value: item.value,
            label: t(item.labelKey)
          }))}
        />
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

      {loaded && !error && hasUsage ? (
        <div className="relative mt-4 min-h-0 flex-1 overflow-hidden">
          <div
            className={[
              'absolute inset-0 flex min-h-0 flex-col overflow-hidden',
              tab === 'overview' ? 'visible' : 'hidden'
            ].join(' ')}
          >
            <div className="grid shrink-0 grid-cols-2 gap-2 sm:grid-cols-4">
              <StatTile label={t('usageHeroStatTokens')} value={formatCompactNumber(totalTokens)} />
              <StatTile
                label={t('usageHeroStatTurns')}
                value={String(summary?.totals.turns ?? 0)}
              />
              <StatTile label={t('usageHeroStatActiveDays')} value={String(activeDays)} />
              <StatTile
                label={t('usageHeroStatTopModel')}
                value={topModelName}
                scrollValue
                title={topModel ? formatComposerModelLabel(topModel.model, composerModelMeta) : undefined}
              />
            </div>
            <div className="mt-3 flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-2xl border border-ds-border/70 bg-ds-card/50 px-3 py-3">
              <UsageActivityHeatmap daily={heatmapDaily} asOfDay={heatmapAsOfDay} fillHeight />
            </div>
          </div>
          <div
            className={[
              'absolute inset-0 flex min-h-0 flex-col',
              tab === 'models' ? 'visible' : 'hidden'
            ].join(' ')}
          >
            <div className="shrink-0 rounded-2xl border border-ds-border/70 bg-ds-card/50 px-3 py-3">
              <p className="mb-3 text-[12px] font-medium text-ds-muted">{t('usageHeroChartTitle')}</p>
              <ModelUsageTrendChart
                daily={daily}
                composerModelMeta={composerModelMeta}
                compact
                showYAxis
                segmentDays={segmentDays}
              />
            </div>
            <p className="mb-2 mt-3 shrink-0 text-[12px] font-medium text-ds-muted">
              {t('usageHeroModelListTitle')}
            </p>
            <div className="ds-trending-grid-scroll min-h-0 flex-1 space-y-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
              {modelBuckets.map((bucket, index) => {
                const share =
                  totalTokens > 0
                    ? ((bucket.totalTokens / totalTokens) * 100).toFixed(1)
                    : '0.0'
                const shortName = formatUsageModelName(bucket.model, composerModelMeta)
                const fullName = formatComposerModelLabel(bucket.model, composerModelMeta)
                return (
                  <div
                    key={bucket.model}
                    className="flex items-center gap-2 rounded-xl px-2 py-2 text-[12.5px] hover:bg-ds-elevated/70"
                  >
                    <span
                      className="h-2.5 w-2.5 shrink-0 rounded-[3px]"
                      style={{
                        backgroundColor:
                          MODEL_USAGE_BAR_COLORS[index % MODEL_USAGE_BAR_COLORS.length]
                      }}
                    />
                    <span
                      className="min-w-0 flex-1 truncate font-medium text-ds-ink"
                      title={fullName}
                    >
                      {shortName}
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
        </div>
      ) : null}
    </div>
  )
}

function StatTile({
  label,
  value,
  scrollValue = false,
  title
}: {
  label: string
  value: string
  scrollValue?: boolean
  title?: string
}): ReactElement {
  return (
    <div className="min-w-0 rounded-2xl border border-ds-border/70 bg-ds-card/55 px-3 py-2">
      <p className="text-[10px] font-medium uppercase tracking-[0.06em] text-ds-faint">{label}</p>
      {scrollValue ? (
        <div
          className="mt-1 overflow-x-auto whitespace-nowrap [scrollbar-width:thin]"
          title={title ?? value}
        >
          <p className="text-[14px] font-semibold tabular-nums text-ds-ink">{value}</p>
        </div>
      ) : (
        <p className="mt-0.5 text-[14px] font-semibold tabular-nums text-ds-ink">{value}</p>
      )}
    </div>
  )
}
