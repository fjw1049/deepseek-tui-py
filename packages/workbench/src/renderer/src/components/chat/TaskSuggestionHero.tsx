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

const EMPTY_HERO_PANEL_CLASS = 'ds-empty-hero-panel'
const TRENDING_REPO_LIMIT = 8
const VISIBLE_TOPIC_COUNT = 2
const CARD_THEMES = [
  {
    border: 'hover:border-emerald-400/35',
    rail: 'from-emerald-400/65 via-cyan-400/25 to-transparent',
    rank: 'border-emerald-400/25 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
    action: 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'
  },
  {
    border: 'hover:border-sky-400/35',
    rail: 'from-sky-400/65 via-blue-400/25 to-transparent',
    rank: 'border-sky-400/25 bg-sky-500/10 text-sky-700 dark:text-sky-300',
    action: 'bg-sky-500/10 text-sky-700 dark:text-sky-300'
  },
  {
    border: 'hover:border-violet-400/35',
    rail: 'from-violet-400/65 via-fuchsia-400/20 to-transparent',
    rank: 'border-violet-400/25 bg-violet-500/10 text-violet-700 dark:text-violet-300',
    action: 'bg-violet-500/10 text-violet-700 dark:text-violet-300'
  },
  {
    border: 'hover:border-amber-400/35',
    rail: 'from-amber-400/70 via-orange-400/25 to-transparent',
    rank: 'border-amber-400/25 bg-amber-500/10 text-amber-700 dark:text-amber-300',
    action: 'bg-amber-500/10 text-amber-700 dark:text-amber-300'
  }
] as const

type Props = {
  onSelectSuggestion?: (prompt: string) => void
}

function RepoMetrics({ repo }: { repo: TrendingRepo }): ReactElement {
  return (
    <div className="flex shrink-0 items-center gap-x-2.5 text-[10.5px] font-medium tabular-nums text-ds-faint">
      <span className="inline-flex items-center gap-1">
        <Star className="h-3 w-3" strokeWidth={1.7} aria-hidden />
        {repo.stars || '—'}
      </span>
      <span className="inline-flex items-center gap-1 text-emerald-600 dark:text-emerald-300">
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
          className="inline-flex min-w-0 max-w-[104px] shrink-0 items-center gap-0.5 rounded-md border border-accent/12 bg-accent/5 px-1.5 py-0.5 text-[10px] font-medium text-ds-muted"
        >
          <span className="shrink-0 font-semibold text-accent">#</span>
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
  const theme = CARD_THEMES[(repo.rank - 1) % CARD_THEMES.length]
  const { owner, repo: repoName } = splitRepoName(repo.name)

  return (
    <div
      className={[
        'group relative flex min-h-[88px] overflow-hidden rounded-[12px] border border-ds-border bg-ds-card/82 shadow-sm transition duration-200 hover:-translate-y-0.5 hover:bg-ds-elevated hover:shadow-[0_14px_28px_rgba(15,23,42,0.08)]',
        theme.border
      ].join(' ')}
    >
      <div className={['pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r', theme.rail].join(' ')} />
      <button
        type="button"
        onClick={() => onAnalyze(repo)}
        className="relative flex min-w-0 flex-1 flex-col px-3.5 py-2.5 text-left"
      >
        <div className="flex min-w-0 items-center gap-2 pr-7">
          <span
            className={[
              'inline-flex h-4 shrink-0 items-center rounded-md border px-1 text-[8px] font-semibold tabular-nums',
              theme.rank
            ].join(' ')}
          >
            #{repo.rank}
          </span>
          <h3 className="min-w-0 flex-1 truncate text-[14.5px] font-semibold leading-tight tracking-[-0.01em] text-ds-ink">
            {owner ? <span className="font-medium text-ds-muted">{owner}</span> : null}
            {repoName}
          </h3>
        </div>
        <p className="mt-1.5 w-full min-w-0 shrink-0 truncate text-[12px] leading-normal text-ds-muted">
          {repo.description || t('trendingNoDescription')}
        </p>
        <div className="mt-auto flex min-w-0 items-center gap-2 pt-2">
          <RepoTopics topics={repo.topics} fallback={t('trendingRepoFallbackTopic')} />
          <div className="ml-auto shrink-0">
            <RepoMetrics repo={repo} />
          </div>
        </div>
      </button>
      <button
        type="button"
        title={t('trendingOpenGithub')}
        aria-label={`${t('trendingOpenGithub')}: ${repo.name}`}
        onClick={() => void window.dsGui.openExternal(repo.url)}
        className="absolute right-0 top-0 flex h-8 w-8 shrink-0 items-center justify-center rounded-bl-[12px] rounded-tr-[12px] text-ds-faint transition hover:bg-ds-card hover:text-accent"
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
    <div className="ds-trending-grid-scroll ds-scroll-surface flex h-full flex-col gap-2 overflow-y-auto overscroll-contain pr-1">
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
  const [usageTab, setUsageTab] = useState<'overview' | 'models'>('overview')
  const [usageRange, setUsageRange] = useState<UsageRange>('90d')
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
          tab={usageTab}
          onTabChange={setUsageTab}
          composerModelMeta={composerModelMeta}
        />

        <div
          className={[
            'ds-hero-panel ds-glass ds-content-card--interactive flex flex-col overflow-hidden rounded-[14px] px-4 py-4 sm:px-5 sm:py-5',
            EMPTY_HERO_PANEL_CLASS
          ].join(' ')}
        >
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <h2 className="text-[16px] font-semibold tracking-[-0.02em] text-ds-ink">
                {t('emptyHeroBadge')}
              </h2>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <GlassSegmentedControl
                value={period}
                onChange={setPeriod}
                items={PERIODS.map((item) => ({ value: item.value, label: t(item.labelKey) }))}
                segmentClassName="px-2.5 py-1 text-[11px]"
              />
              <button
                type="button"
                title={t('trendingRetry')}
                aria-label={t('trendingRetry')}
                onClick={() => setReloadKey((value) => value + 1)}
                className="inline-flex h-8 w-8 items-center justify-center rounded-full border border-ds-border bg-ds-elevated text-ds-muted transition hover:border-accent/25 hover:text-accent"
              >
                <RefreshCw className={['h-3.5 w-3.5', loading ? 'animate-spin' : ''].join(' ')} strokeWidth={1.8} />
              </button>
            </div>
          </div>

          <div className="relative mt-3 min-h-0 flex-1">
            {loading ? (
              <div className="ds-trending-grid-scroll flex h-full flex-col gap-2 pr-1">
                {Array.from({ length: 3 }).map((_, index) => (
                  <div
                    key={index}
                    className="min-h-[88px] animate-pulse rounded-[12px] border border-ds-border bg-ds-card/60"
                  />
                ))}
              </div>
            ) : error ? (
              <div className="rounded-[14px] border border-ds-border bg-ds-card/75 px-4 py-4 text-left">
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
