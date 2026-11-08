import { useState, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import cover from '../../assets/ai-profile-cover.png'
import { useChatStore } from '../../store/chat-store'
import { usePersistentUsage } from '../../hooks/use-persistent-usage'
import { formatCompactNumber } from '../../hooks/use-model-usage'
import { UsageActivityHeatmap } from './UsageActivityHeatmap'
import { ModelUsageTrendChart } from './ModelUsageTrendChart'
import { GlassSegmentedControl } from './GlassSegmentedControl'

export function AiProfileSettingsPanel(): ReactElement {
  const { t } = useTranslation('settings')
  const [chartRange, setChartRange] = useState<'30' | '90' | '365'>('365')
  const refreshKey = useChatStore((state) => state.usageRefreshKey)
  const modelMeta = useChatStore((state) => state.composerModelMeta)
  const usage = usePersistentUsage('1y', refreshKey)
  const daily = usage.data?.daily ?? []
  const chartSegmentDays = chartRange === '365' ? 7 : chartRange === '90' ? 3 : 1
  const chartGranularity = t('aiProfile.chartGranularity', { days: chartSegmentDays })
  const chartDaily = daily.slice(-Number(chartRange))
  const chartTokens = chartDaily.reduce((sum, day) => sum + day.totalTokens, 0)
  const chartRanges = [
    { value: '30' as const, label: t('aiProfile.month') },
    { value: '90' as const, label: t('aiProfile.quarter') },
    { value: '365' as const, label: t('aiProfile.year') }
  ]
  const summary = usage.data?.summary
  const ready = usage.loaded && !usage.error
  const tokens = summary?.totals.totalTokens ?? 0
  const activeDays = daily.filter((day) => day.totalTokens > 0).length
  const metrics = [
    { label: t('aiProfile.input'), value: summary?.totals.inputTokens ?? 0 },
    { label: t('aiProfile.output'), value: summary?.totals.outputTokens ?? 0 },
    { label: t('aiProfile.peak'), value: Math.max(0, ...daily.map((day) => day.totalTokens)) },
    { label: t('aiProfile.activeDays'), value: activeDays }
  ]


  return (
    <div className="ds-settings-page ds-page-scroll ds-no-drag h-full min-h-0 min-w-0 flex-1 overflow-y-auto [scrollbar-gutter:stable] px-8 py-10 sm:px-10">
      <div className="mx-auto flex max-w-[836px] flex-col gap-5">
        <header className="mb-3">
          <h1 className="text-2xl font-semibold tracking-tight text-ds-ink">{t('aiProfile.title')}</h1>
          <p className="mt-1 text-[14px] text-ds-muted">{t('aiProfile.subtitle')}</p>
        </header>
        <section className="ds-content-card overflow-hidden rounded-2xl">
          <img src={cover} alt="" className="h-[112px] w-full object-cover object-center" />
          <div className="relative flex flex-col gap-4 px-5 pb-5">
            <div className="-mt-8 flex items-end justify-between gap-3">
              <div aria-hidden className="flex h-16 w-16 shrink-0 items-center justify-center rounded-full bg-ds-card text-2xl font-medium text-ds-muted">D</div>
            </div>
            <div>
              <h2 className="text-[16px] font-semibold text-ds-ink">{t('aiProfile.workspace')}</h2>
            </div>
            <div aria-live="polite" aria-busy={usage.loading}>
              <p className="text-sm text-ds-muted">{t('aiProfile.tokens')}</p>
              <p className="mt-1 text-3xl font-semibold tabular-nums text-ds-ink">{ready ? formatCompactNumber(tokens) : '—'}</p>
            </div>
            <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {metrics.map((metric) => (
                <div key={metric.label} className="rounded-xl bg-ds-subtle p-3">
                  <dd className="text-sm font-medium tabular-nums text-ds-ink">{ready ? formatCompactNumber(metric.value) : '—'}</dd>
                  <dt className="mt-1 text-xs text-ds-muted">{metric.label}</dt>
                </div>
              ))}
            </dl>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-sm font-medium text-ds-muted">{t('aiProfile.activity')}</h2>
            </div>
            <div aria-busy={usage.loading}>
              <div className="flex h-[210px] flex-col">
                <UsageActivityHeatmap daily={daily} asOfDay={usage.data?.asOfDay} fillHeight />
              </div>
              <div className="mt-2 min-h-6 text-sm" aria-live="polite">
                {usage.error ? (
                  <p role="alert" className="text-red-500">{t('aiProfile.error', { message: usage.error })}</p>
                ) : (
                  <p role="status" className="text-ds-muted">
                    {usage.loading ? t('aiProfile.loading') : usage.data?.summary?.totals.totalTokens === 0 ? t('aiProfile.empty') : '\u00a0'}
                  </p>
                )}
              </div>
            </div>
          </div>
        </section>
        <div className="flex flex-col gap-4" aria-busy={usage.loading}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-sm font-medium text-ds-muted">{t('aiProfile.chartPeriod')}</h2>
              <GlassSegmentedControl value={chartRange} onChange={setChartRange} items={chartRanges} ariaLabel={t('aiProfile.chartPeriod')} />
            </div>
            <section className="overflow-hidden rounded-[20px] bg-ds-subtle px-4 pb-4 pt-4">
              <h2 className="text-sm text-ds-muted">{t('aiProfile.bars')}</h2>
              <p className="mt-1 text-xs text-ds-muted">{chartGranularity}</p>
              <p className="mb-3 mt-0.5 text-xl font-medium tabular-nums text-ds-ink">{ready ? formatCompactNumber(chartTokens) : '—'} tokens</p>
              <div><ModelUsageTrendChart segmentDays={chartSegmentDays} daily={chartDaily} composerModelMeta={modelMeta} colorScheme="purple" showYAxis={false} /></div>
            </section>
            <section className="overflow-hidden rounded-[20px] bg-ds-subtle px-4 pb-4 pt-4">
              <h2 className="text-sm text-ds-muted">{t('aiProfile.trend')}</h2>
              <p className="mb-3 mt-1 text-xs text-ds-faint">{t('aiProfile.lineDescription', { days: chartRange })} · {chartGranularity}</p>
              <div><ModelUsageTrendChart segmentDays={chartSegmentDays} daily={chartDaily} composerModelMeta={modelMeta} variant="line" colorScheme="purple" showYAxis={false} /></div>
            </section>
        </div>
      </div>
    </div>
  )
}
