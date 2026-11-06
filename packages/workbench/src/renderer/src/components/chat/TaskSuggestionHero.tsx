import type { ReactElement } from 'react'
import { useEffect, useState } from 'react'
import {
  Bot,
  ExternalLink,
  RefreshCw,
  Star,
  TrendingUp
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { TrendingPeriod, TrendingRepo } from '../../../../shared/ds-gui-api'
import type { UsageRange } from '@shared/usage-ledger'
import { useChatStore } from '../../store/chat-store'
import { usePersistentUsage } from '../../hooks/use-persistent-usage'
import { ModelUsageHeroPanel } from '../settings/ModelUsageHeroPanel'
import { GlassSegmentedControl } from '../settings/GlassSegmentedControl'
import { GreetingDateBar } from './GreetingDateBar'

const PERIODS: Array<{ value: TrendingPeriod; labelKey: string }> = [
  { value: 'daily', labelKey: 'trendingDaily' },
  { value: 'weekly', labelKey: 'trendingWeekly' },
  { value: 'monthly', labelKey: 'trendingMonthly' }
]

const TRENDING_REPO_LIMIT = 8
const VISIBLE_TOPIC_COUNT = 2
type Props = {
  onSelectSuggestion?: (prompt: string) => void
}

function RepoMetrics({ repo }: { repo: TrendingRepo }): ReactElement {
  return (
    <div className="flex shrink-0 items-center gap-x-2.5 text-[10.5px] font-medium tabular-nums text-ds-muted">
      <span className="inline-flex items-center gap-1">
        <Star className="h-3 w-3" strokeWidth={1.7} aria-hidden />
        {repo.stars || '—'}
      </span>
      <span className="inline-flex items-center gap-1 text-ds-success">
        <TrendingUp className="h-3 w-3" strokeWidth={1.7} aria-hidden />
        {repo.gained || '—'}
      </span>
    </div>
  )
}

function RepoTopics({ topics, fallback }: { topics: string[]; fallback: string }): ReactElement {
  const visibleTopics = topics.slice(0, VISIBLE_TOPIC_COUNT)
  const labels = visibleTopics.length > 0 ? visibleTopics : [fallback]

  return (
    <div className="flex min-w-0 items-center gap-1.5 overflow-hidden">
      {labels.map((topic) => (
        <span
          key={topic}
          className="inline-flex min-w-0 max-w-[104px] items-center gap-0.5 text-[10.5px] text-ds-muted"
        >
          <span className="shrink-0 text-ds-faint">#</span>
          <span className="min-w-0 truncate">{topic}</span>
        </span>
      ))}
    </div>
  )
}

/** Split "owner/repo" into a de-emphasized owner prefix and an emphasized repo name. */
function splitRepoName(name: string): { owner: string; repo: string } {
  const slash = name.lastIndexOf('/')
  if (slash <= 0 || slash === name.length - 1) return { owner: '', repo: name }
  return { owner: name.slice(0, slash + 1), repo: name.slice(slash + 1) }
}

function RepoRow({
  repo,
  onAnalyze
}: {
  repo: TrendingRepo
  onAnalyze: (repo: TrendingRepo) => void
}): ReactElement {
  const { t } = useTranslation('common')
  const { owner, repo: repoName } = splitRepoName(repo.name)

  return (
    <div className="relative flex shrink-0 border-b border-ds-border/60 last:border-b-0 hover:bg-ds-subtle focus-within:bg-ds-subtle">
      <button
        type="button"
        onClick={() => onAnalyze(repo)}
        className="flex min-w-0 flex-1 items-baseline gap-2 rounded-md px-1 py-3 text-left focus-visible:outline-offset-[-2px]"
      >
        <span className="w-5 shrink-0 text-center text-[12px] font-medium tabular-nums text-ds-muted">
          {repo.rank}
        </span>
        <div className="min-w-0 flex-1">
          <h3 title={repo.name} className="flex min-w-0 pr-7 text-[14px] font-semibold leading-tight tracking-[-0.01em] text-ds-ink">
            {owner ? <span className="max-w-[45%] truncate font-medium text-ds-muted">{owner}</span> : null}
            <span className="truncate">{repoName}</span>
          </h3>
          <p className="mt-1 truncate text-[12px] leading-normal text-ds-muted">
            {repo.description || t('trendingNoDescription')}
          </p>
          <div className="mt-1.5 flex min-w-0 items-center justify-between gap-3">
            <RepoTopics topics={repo.topics} fallback={t('trendingRepoFallbackTopic')} />
            <RepoMetrics repo={repo} />
          </div>
        </div>
      </button>
      <button
        type="button"
        title={t('trendingOpenGithub')}
        aria-label={`${t('trendingOpenGithub')}: ${repo.name}`}
        onClick={() => void window.dsGui.openExternal(repo.url)}
        className="absolute right-0 top-1 flex h-8 w-8 items-center justify-center rounded-md text-ds-muted transition-colors hover:bg-ds-hover hover:text-ds-ink"
      >
        <ExternalLink className="h-3.5 w-3.5" strokeWidth={1.8} />
      </button>
    </div>
  )
}

function TrendingRepoScrollList({
  repos,
  onAnalyze
}: {
  repos: TrendingRepo[]
  onAnalyze: (repo: TrendingRepo) => void
}): ReactElement {
  return (
    <div className="ds-trending-grid-scroll ds-scroll-surface flex h-full flex-col overflow-y-auto overscroll-contain pr-1">
      {repos.map((repo) => (
        <RepoRow key={repo.name} repo={repo} onAnalyze={onAnalyze} />
      ))}
    </div>
  )
}

export function TaskSuggestionHero({ onSelectSuggestion }: Props): ReactElement {
  const { t } = useTranslation('common')
  const usageRefreshKey = useChatStore((s) => s.usageRefreshKey)
  const composerModelMeta = useChatStore((s) => s.composerModelMeta)
  const [usageRange, setUsageRange] = useState<UsageRange>('1y')
  const persistentUsage = usePersistentUsage(usageRange, usageRefreshKey)
  const heatmapUsage = usePersistentUsage('1y', usageRefreshKey)
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
  const trendingRepos = repos.slice(0, TRENDING_REPO_LIMIT)

  return (
    <div className="ds-no-drag w-full">
      <div className="mt-4">
        <GreetingDateBar
          daily={persistentUsage.data?.daily ?? []}
          asOfDay={persistentUsage.data?.asOfDay}
          loading={persistentUsage.loading}
        />
      </div>
      <div className="ds-empty-hero-grid mt-6 grid">
        <ModelUsageHeroPanel
          summary={persistentUsage.data?.summary ?? null}
          daily={persistentUsage.data?.daily ?? []}
          heatmapDaily={heatmapUsage.data?.daily ?? []}
          heatmapAsOfDay={heatmapUsage.data?.asOfDay}
          loading={persistentUsage.loading || heatmapUsage.loading}
          loaded={persistentUsage.loaded && heatmapUsage.loaded}
          error={persistentUsage.error ?? heatmapUsage.error}
          range={usageRange}
          onRangeChange={setUsageRange}
          composerModelMeta={composerModelMeta}
        />

        <div className="ds-hero-panel ds-glass ds-empty-hero-panel flex flex-col overflow-hidden rounded-[14px] p-4 sm:p-5">
          <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
            <h2 className="text-[15px] font-semibold tracking-[-0.02em] text-ds-ink">
              {t('emptyHeroBadge')}
            </h2>
            <div className="flex shrink-0 items-center gap-1">
              <GlassSegmentedControl
                value={period}
                onChange={setPeriod}
                items={PERIODS.map((item) => ({ value: item.value, label: t(item.labelKey) }))}
                ariaLabel={t('emptyHeroBadge')}
                className="ds-hero-ranges"
                segmentClassName="px-2 py-1"
              />
              <button
                type="button"
                title={t('trendingRetry')}
                aria-label={t('trendingRetry')}
                onClick={() => setReloadKey((value) => value + 1)}
                className="inline-flex h-8 w-8 items-center justify-center rounded-full text-ds-muted transition-colors hover:bg-ds-hover hover:text-ds-ink"
              >
                <RefreshCw className={['h-3.5 w-3.5', loading ? 'animate-spin' : ''].join(' ')} strokeWidth={1.8} />
              </button>
            </div>
          </div>

          <div className="relative mt-3 min-h-0 flex-1 border-t border-ds-border/60">
            {loading ? (
              <div className="ds-trending-grid-scroll flex h-full flex-col gap-2 pr-1">
                {Array.from({ length: 3 }).map((_, index) => (
                  <div
                    key={index}
                    className="mt-2 min-h-16 animate-pulse rounded-md bg-ds-subtle"
                  />
                ))}
              </div>
            ) : error ? (
              <div className="py-4 text-left">
                <p className="text-[13px] font-medium text-ds-ink">{t('trendingError')}</p>
                <p className="mt-1 text-[12px] leading-5 text-ds-muted">{error}</p>
              </div>
            ) : (
              <TrendingRepoScrollList repos={trendingRepos} onAnalyze={analyzeRepo} />
            )}
          </div>
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
      <div className="ds-card-soft mb-4 rounded-[12px] px-4 py-3">
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
