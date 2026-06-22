import type { ReactElement } from 'react'
import { useEffect, useState } from 'react'
import {
  Bot,
  ExternalLink,
  Flame,
  RefreshCw,
  Star,
  TrendingUp
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { TrendingPeriod, TrendingRepo } from '../../../../shared/ds-gui-api'

const PERIODS: Array<{ value: TrendingPeriod; labelKey: string }> = [
  { value: 'daily', labelKey: 'trendingDaily' },
  { value: 'weekly', labelKey: 'trendingWeekly' },
  { value: 'monthly', labelKey: 'trendingMonthly' }
]

type Props = {
  onSelectSuggestion?: (prompt: string) => void
}

function RepoMetrics({ repo }: { repo: TrendingRepo }): ReactElement {
  const { t } = useTranslation('common')
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-ds-faint">
      <span className="inline-flex items-center gap-1">
        <Star className="h-3.5 w-3.5" strokeWidth={1.7} aria-hidden />
        {repo.stars || '—'}
      </span>
      <span className="inline-flex items-center gap-1 text-emerald-600 dark:text-emerald-300">
        <TrendingUp className="h-3.5 w-3.5" strokeWidth={1.7} aria-hidden />
        {repo.gained || '—'} {t('trendingGained')}
      </span>
      {repo.isNew ? (
        <span className="rounded-full bg-rose-500/10 px-1.5 py-0.5 text-[10px] font-semibold text-rose-600 dark:text-rose-300">
          {t('trendingNew')}
        </span>
      ) : null}
    </div>
  )
}

function RepoRow({
  repo,
  onAnalyze
}: {
  repo: TrendingRepo
  onAnalyze: (repo: TrendingRepo) => void
}): ReactElement {
  const { t } = useTranslation('common')
  return (
    <div className="group flex h-full min-h-0 rounded-[14px] border border-ds-border bg-ds-card/72 transition hover:border-accent/25 hover:bg-ds-elevated">
      <button
        type="button"
        onClick={() => onAnalyze(repo)}
        className="flex min-w-0 flex-1 items-center gap-3 px-3.5 py-3 text-left"
      >
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-[10px] bg-accent/10 text-[12px] font-semibold text-accent">
          {repo.rank}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-2">
            <div className="min-w-0 flex-1 truncate text-[14px] font-semibold tracking-[-0.01em] text-ds-ink">
              {repo.name}
            </div>
            {repo.isNew ? (
              <span className="shrink-0 rounded-full bg-rose-500/10 px-1.5 py-0.5 text-[10px] font-semibold text-rose-600 dark:text-rose-300">
                {t('trendingNew')}
              </span>
            ) : null}
          </div>
          <div className="mt-1 flex min-w-0 items-center gap-3">
            <RepoMetrics repo={{ ...repo, isNew: false }} />
            {repo.topics[0] ? (
              <span className="hidden max-w-[132px] truncate rounded-full bg-ds-elevated px-2 py-0.5 text-[10.5px] text-ds-muted sm:inline">
                {repo.topics[0]}
              </span>
            ) : null}
          </div>
          <p className="mt-1 line-clamp-1 text-[12px] leading-5 text-ds-muted">
            {repo.description || t('trendingNoDescription')}
          </p>
        </div>
      </button>
      <button
        type="button"
        title={t('trendingOpenGithub')}
        aria-label={`${t('trendingOpenGithub')}: ${repo.name}`}
        onClick={() => void window.dsGui.openExternal(repo.url)}
        className="flex w-10 shrink-0 items-start justify-center rounded-r-[14px] pt-3 text-ds-faint transition hover:bg-ds-card hover:text-accent"
      >
        <ExternalLink className="h-4 w-4" strokeWidth={1.8} />
      </button>
    </div>
  )
}

export function TaskSuggestionHero({ onSelectSuggestion }: Props): ReactElement {
  const { t } = useTranslation('common')
  const [period, setPeriod] = useState<TrendingPeriod>('daily')
  const [repos, setRepos] = useState<TrendingRepo[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    window.dsGui
      .getTrendingRepos(period)
      .then((result) => {
        if (cancelled) return
        if (result.ok) {
          setRepos(result.repos)
          setError(null)
        } else {
          setRepos([])
          setError(result.error)
        }
      })
      .catch((caught: unknown) => {
        if (cancelled) return
        setRepos([])
        setError(caught instanceof Error ? caught.message : String(caught))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [period, reloadKey])

  const analyzeRepo = (repo: TrendingRepo): void => {
    onSelectSuggestion?.(t('trendingAnalyzePrompt', { name: repo.name, url: repo.url }))
  }

  return (
    <div className="ds-no-drag w-full">
      <div className="ds-hero-panel ds-glass flex w-full flex-col overflow-hidden rounded-[22px] px-5 py-6 sm:px-6 lg:h-[360px]">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0 flex-1 text-left">
            <div className="mb-2 flex items-center gap-1.5 text-accent">
              <Flame className="h-4 w-4 shrink-0" strokeWidth={1.8} aria-hidden />
              <span className="text-[13px] font-semibold">{t('emptyHeroBadge')}</span>
            </div>
            <h1 className="text-[22px] font-semibold tracking-[-0.03em] text-ds-ink sm:text-[24px]">
              {t('emptyHeroTitle')}
            </h1>
            <p className="mt-2 max-w-[640px] text-[14px] leading-7 text-ds-muted">{t('emptyHeroSub')}</p>
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            <div className="inline-flex rounded-full border border-ds-border bg-ds-elevated p-1">
              {PERIODS.map((item) => (
                <button
                  key={item.value}
                  type="button"
                  onClick={() => setPeriod(item.value)}
                  className={[
                    'rounded-full px-3 py-1.5 text-[12px] font-medium transition',
                    period === item.value
                      ? 'bg-accent text-white shadow-sm'
                      : 'text-ds-muted hover:text-ds-ink'
                  ].join(' ')}
                >
                  {t(item.labelKey)}
                </button>
              ))}
            </div>
            <button
              type="button"
              title={t('trendingRetry')}
              aria-label={t('trendingRetry')}
              onClick={() => setReloadKey((value) => value + 1)}
              className="inline-flex h-9 w-9 items-center justify-center rounded-full border border-ds-border bg-ds-elevated text-ds-muted transition hover:border-accent/25 hover:text-accent"
            >
              <RefreshCw className={['h-4 w-4', loading ? 'animate-spin' : ''].join(' ')} strokeWidth={1.8} />
            </button>
          </div>
        </div>

        <div className="mt-4 h-[288px] min-h-0 overflow-y-auto pr-1 lg:h-[188px]">
          {loading ? (
            <div className="grid auto-rows-[88px] grid-cols-1 gap-3 lg:grid-cols-2">
              {Array.from({ length: 6 }).map((_, index) => (
                <div
                  key={index}
                  className="h-full animate-pulse rounded-[14px] border border-ds-border bg-ds-card/60 px-3.5 py-3"
                >
                  <div className="flex items-start gap-2.5">
                    <div className="h-7 w-7 rounded-[9px] bg-ds-elevated" />
                    <div className="min-w-0 flex-1">
                      <div className="h-4 w-2/3 rounded bg-ds-elevated" />
                      <div className="mt-2 h-3 w-1/2 rounded bg-ds-elevated" />
                    </div>
                  </div>
                  <div className="mt-4 h-3 w-full rounded bg-ds-elevated" />
                  <div className="mt-2 h-3 w-4/5 rounded bg-ds-elevated" />
                </div>
              ))}
            </div>
          ) : error ? (
            <div className="rounded-[14px] border border-ds-border bg-ds-card/75 px-4 py-5 text-left">
              <p className="text-[14px] font-medium text-ds-ink">{t('trendingError')}</p>
              <p className="mt-1 text-[12px] leading-5 text-ds-muted">{error}</p>
              <button
                type="button"
                onClick={() => setReloadKey((value) => value + 1)}
                className="mt-3 inline-flex items-center gap-2 rounded-full border border-ds-border bg-ds-elevated px-3 py-1.5 text-[12px] font-medium text-ds-ink transition hover:border-accent/25 hover:text-accent"
              >
                <RefreshCw className="h-3.5 w-3.5" strokeWidth={1.8} />
                {t('trendingRetry')}
              </button>
            </div>
          ) : (
            <div className="grid auto-rows-[88px] grid-cols-1 gap-3 lg:grid-cols-2">
              {repos.map((repo) => (
                <RepoRow key={repo.name} repo={repo} onAnalyze={analyzeRepo} />
              ))}
            </div>
          )}
        </div>

      </div>
    </div>
  )
}

type OfflineProps = {
  onRetry: () => void
  onOpenSettings: () => void
  onOpenDiagnostics: () => void
}

export function TaskSuggestionOfflineHero({
  onRetry,
  onOpenSettings,
  onOpenDiagnostics
}: OfflineProps): ReactElement {
  const { t } = useTranslation('common')
  return (
    <div className="flex flex-col items-center justify-center px-8 py-16 text-center">
      <div className="ds-card-soft mb-4 rounded-[18px] px-4 py-3">
        <Bot className="mx-auto h-6 w-6 text-accent opacity-90" strokeWidth={1.4} />
      </div>
      <p className="max-w-sm text-[20px] font-semibold tracking-[-0.03em] text-ds-ink">
        {t('runtimeOfflineHeroTitle')}
      </p>
      <p className="mt-2 max-w-[520px] text-[14px] leading-6 text-ds-muted">{t('runtimeOfflineHeroSub')}</p>
      <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
        <button
          type="button"
          className="ds-chip rounded-full px-4 py-2 text-[12.5px] font-medium text-ds-ink"
          onClick={onRetry}
        >
          {t('retryConnection')}
        </button>
        <button
          type="button"
          className="ds-chip-muted rounded-full px-4 py-2 text-[12.5px] font-medium text-ds-muted"
          onClick={onOpenDiagnostics}
        >
          {t('runtimeDiagnosticsButton')}
        </button>
        <button
          type="button"
          className="ds-chip-muted rounded-full px-4 py-2 text-[12.5px] font-medium text-ds-muted"
          onClick={onOpenSettings}
        >
          {t('openSettings')}
        </button>
      </div>
    </div>
  )
}
