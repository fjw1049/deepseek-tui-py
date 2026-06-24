import { useMemo, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { BarChart3 } from 'lucide-react'
import { formatComposerModelLabel } from '../../lib/composer-model-label'
import type { ComposerModelMeta } from '../../lib/composer-model-label'
import {
  formatCompactNumber,
  formatCost,
  type ModelUsageSummary
} from '../../hooks/use-model-usage'

const BAR_COLORS = ['#6f8cff', '#52b788', '#f2b56b', '#c69bd3', '#8b7cf6', '#67b7dc']

type Props = {
  usage: ModelUsageSummary | null
  loading: boolean
  loaded: boolean
  error: string | null
  runtimeReady: boolean
  activeModelId?: string
  composerModelMeta: Record<string, ComposerModelMeta>
}

export function ModelUsagePanel({
  usage,
  loading,
  loaded,
  error,
  runtimeReady,
  activeModelId = '',
  composerModelMeta
}: Props): ReactElement {
  const { t, i18n } = useTranslation('settings')
  const buckets = usage?.buckets ?? []
  const maxTokens = useMemo(
    () => Math.max(...buckets.map((bucket) => bucket.totalTokens), 1),
    [buckets]
  )

  return (
    <div className="px-4 py-5">
      <div className="flex items-start gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-ds-subtle text-ds-muted">
          <BarChart3 className="h-4 w-4" strokeWidth={1.85} />
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="text-[14px] font-semibold text-ds-ink">{t('modelUsageTitle')}</h3>
          <p className="mt-1 text-[13px] leading-6 text-ds-muted">{t('modelUsageDesc')}</p>
        </div>
        {usage ? (
          <div className="shrink-0 text-right text-[12px] tabular-nums text-ds-muted">
            <div>{t('modelUsageTotalTokens', { tokens: formatCompactNumber(usage.totals.totalTokens) })}</div>
            <div className="mt-0.5">
              {t('modelUsageTotalCost', {
                cost: formatCost(usage.totals.costUsd, i18n.language, usage.totals.costCny)
              })}
            </div>
          </div>
        ) : null}
      </div>

      {loading && !loaded ? (
        <p className="mt-4 text-[13px] text-ds-faint">{t('modelUsageLoading')}</p>
      ) : null}

      {!runtimeReady ? (
        <p className="mt-4 rounded-xl border border-dashed border-amber-300/70 bg-amber-50/70 px-4 py-5 text-[13px] leading-6 text-amber-900 dark:border-amber-700/50 dark:bg-amber-950/25 dark:text-amber-100">
          {t('modelUsageNeedRuntime')}
        </p>
      ) : null}

      {runtimeReady && error ? (
        <p className="mt-4 rounded-xl border border-red-300/70 bg-red-50/80 px-4 py-5 text-[13px] leading-6 text-red-800 dark:border-red-800/50 dark:bg-red-950/30 dark:text-red-100">
          {t('modelUsageError', { message: error })}
        </p>
      ) : null}

      {runtimeReady && !error && !loading && loaded && buckets.length === 0 ? (
        <p className="mt-4 rounded-xl border border-dashed border-ds-border px-4 py-5 text-[13px] leading-6 text-ds-muted">
          {t('modelUsageEmpty')}
        </p>
      ) : null}

      {runtimeReady && !error && buckets.length > 0 ? (
        <div className="mt-4 space-y-3">
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
      ) : null}
    </div>
  )
}
