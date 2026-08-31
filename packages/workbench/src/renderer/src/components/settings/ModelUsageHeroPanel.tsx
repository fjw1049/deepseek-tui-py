import { useEffect, useMemo, useRef, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import type { UsageDailyPoint, UsageRange, ModelUsageSummary } from '@shared/usage-ledger'
import {
  formatComposerModelLabel,
  formatUsageModelName
} from '../../lib/composer-model-label'
import type { ComposerModelMeta } from '../../lib/composer-model-label'
import { threadMarqueeDurationMs } from '../../lib/thread-marquee'
import { formatCompactNumber } from '../../hooks/use-model-usage'
import { UsageActivityHeatmap } from './UsageActivityHeatmap'
import { GlassSegmentedControl } from './GlassSegmentedControl'

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
  const totalTokens = summary?.totals.totalTokens ?? 0

  const ranges: Array<{ value: UsageRange; labelKey: string }> = [
    { value: '1y', labelKey: 'usageHeroRangeAll' },
    { value: '30d', labelKey: 'usageHeroRange30d' },
    { value: '7d', labelKey: 'usageHeroRange7d' }
  ]

  return (
    <div className="ds-hero-panel ds-glass ds-content-card--interactive ds-empty-hero-panel flex flex-col overflow-hidden rounded-[14px] px-4 py-4 sm:px-5 sm:py-5">
      <div className="flex shrink-0 flex-nowrap items-center justify-between gap-3">
        <h2 className="text-[14px] font-semibold tracking-[-0.01em] text-ds-ink">
          {t('usageHeroTabOverview')}
        </h2>
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
        <div className="mt-4 flex min-h-0 flex-1 flex-col overflow-hidden">
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
              marqueeValue
              title={topModel ? formatComposerModelLabel(topModel.model, composerModelMeta) : undefined}
            />
          </div>
          <div className="mt-3 flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-2xl border border-ds-border/60 bg-ds-card/40 px-3.5 py-3">
            <UsageActivityHeatmap daily={heatmapDaily} asOfDay={heatmapAsOfDay} fillHeight />
          </div>
        </div>
      ) : null}
    </div>
  )
}

function StatTile({
  label,
  value,
  marqueeValue = false,
  title
}: {
  label: string
  value: string
  marqueeValue?: boolean
  title?: string
}): ReactElement {
  return (
    <div className="min-w-0 rounded-2xl border border-ds-border/60 bg-ds-card/40 px-3 py-2">
      <p className="text-[10px] font-medium uppercase tracking-[0.06em] text-ds-faint">{label}</p>
      {marqueeValue ? (
        <HoverMarqueeValue value={value} title={title ?? value} />
      ) : (
        <p className="mt-0.5 text-[14px] font-semibold tabular-nums text-ds-ink">{value}</p>
      )}
    </div>
  )
}

const MARQUEE_DWELL_MS = 320

function HoverMarqueeValue({ value, title }: { value: string; title: string }): ReactElement {
  const viewportRef = useRef<HTMLDivElement>(null)
  const valueRef = useRef<HTMLParagraphElement>(null)
  const animationRef = useRef<Animation | null>(null)
  const dwellTimerRef = useRef<number | null>(null)

  const clearDwellTimer = (): void => {
    if (dwellTimerRef.current == null) return
    window.clearTimeout(dwellTimerRef.current)
    dwellTimerRef.current = null
  }

  const startMarquee = (): void => {
    clearDwellTimer()
    dwellTimerRef.current = window.setTimeout(() => {
      dwellTimerRef.current = null
      const viewport = viewportRef.current
      const inner = valueRef.current
      if (!viewport || !inner) return
      if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true) return

      const overflow = Math.ceil(inner.scrollWidth - viewport.clientWidth)
      if (overflow <= 1) return

      const currentTransform = window.getComputedStyle(inner).transform
      const previousAnimation = animationRef.current
      if (previousAnimation) previousAnimation.onfinish = null
      previousAnimation?.cancel()
      animationRef.current = inner.animate(
        [
          { transform: currentTransform === 'none' ? 'translateX(0)' : currentTransform },
          { transform: `translateX(-${overflow}px)` }
        ],
        {
          duration: threadMarqueeDurationMs(overflow),
          easing: 'linear',
          fill: 'forwards'
        }
      )
    }, MARQUEE_DWELL_MS)
  }

  const resetMarquee = (): void => {
    clearDwellTimer()
    const inner = valueRef.current
    if (!inner) return

    const currentTransform = window.getComputedStyle(inner).transform
    const previousAnimation = animationRef.current
    if (previousAnimation) previousAnimation.onfinish = null
    previousAnimation?.cancel()
    if (currentTransform === 'none') {
      animationRef.current = null
      return
    }

    const reset = inner.animate(
      [{ transform: currentTransform }, { transform: 'translateX(0)' }],
      { duration: 180, easing: 'ease-out' }
    )
    animationRef.current = reset
    reset.onfinish = () => {
      if (animationRef.current !== reset) return
      reset.cancel()
      animationRef.current = null
    }
  }

  useEffect(
    () => () => {
      clearDwellTimer()
      animationRef.current?.cancel()
    },
    [value]
  )

  return (
    <div
      ref={viewportRef}
      className="mt-0.5 overflow-hidden whitespace-nowrap"
      title={title}
      onMouseEnter={startMarquee}
      onMouseLeave={resetMarquee}
    >
      <p
        ref={valueRef}
        className="inline-block min-w-full w-max text-[14px] font-semibold tabular-nums text-ds-ink"
      >
        {value}
      </p>
    </div>
  )
}
