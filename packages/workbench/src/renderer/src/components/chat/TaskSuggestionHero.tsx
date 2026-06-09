import type { ReactElement } from 'react'
import { useCallback, useEffect, useState } from 'react'
import {
  Bot,
  Bug,
  Box,
  CircleDot,
  FolderSearch,
  GitBranch,
  ListTodo,
  Palette,
  Pen,
  ScanLine,
  Sparkles
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { WorkspaceSuggestion } from '../../../../shared/ds-gui-api'
import { useChatStore } from '../../store/chat-store'

type SuggestionTone = 'blue' | 'emerald' | 'violet' | 'orange'

type StaticSuggestionDef = {
  id: string
  icon: ReactElement
  tone: SuggestionTone
  recommended?: boolean
  titleKey: string
  descKey: string
  flowKey: string
  tagKey: string
  promptKey: string
}

const STATIC_SUGGESTIONS: StaticSuggestionDef[] = [
  {
    id: 'structure',
    icon: <FolderSearch className="h-4 w-4" strokeWidth={1.75} />,
    tone: 'blue',
    recommended: true,
    titleKey: 'promptStructureTitle',
    descKey: 'promptStructureDesc',
    flowKey: 'promptStructureFlow',
    tagKey: 'promptStructureTag',
    promptKey: 'promptStructurePrompt'
  },
  {
    id: 'bug',
    icon: <Bug className="h-4 w-4" strokeWidth={1.75} />,
    tone: 'emerald',
    titleKey: 'promptBugTitle',
    descKey: 'promptBugDesc',
    flowKey: 'promptBugFlow',
    tagKey: 'promptBugTag',
    promptKey: 'promptBugPrompt'
  },
  {
    id: 'plan',
    icon: <Box className="h-4 w-4" strokeWidth={1.75} />,
    tone: 'violet',
    titleKey: 'promptPlanTitle',
    descKey: 'promptPlanDesc',
    flowKey: 'promptPlanFlow',
    tagKey: 'promptPlanTag',
    promptKey: 'promptPlanPrompt'
  },
  {
    id: 'design',
    icon: <Palette className="h-4 w-4" strokeWidth={1.75} />,
    tone: 'orange',
    titleKey: 'promptDesignTitle',
    descKey: 'promptDesignDesc',
    flowKey: 'promptDesignFlow',
    tagKey: 'promptDesignTag',
    promptKey: 'promptDesignPrompt'
  }
]

const ICON_TONE: Record<SuggestionTone, string> = {
  blue: 'bg-blue-500/12 text-blue-600 dark:bg-blue-500/18 dark:text-blue-300',
  emerald: 'bg-emerald-500/12 text-emerald-600 dark:bg-emerald-500/18 dark:text-emerald-300',
  violet: 'bg-violet-500/12 text-violet-600 dark:bg-violet-500/18 dark:text-violet-300',
  orange: 'bg-orange-500/12 text-orange-600 dark:bg-orange-500/18 dark:text-orange-300'
}

const TAG_TONE: Record<SuggestionTone, string> = {
  blue: 'text-blue-600 dark:text-blue-300',
  emerald: 'text-emerald-600 dark:text-emerald-300',
  violet: 'text-violet-600 dark:text-violet-300',
  orange: 'text-orange-600 dark:text-orange-300'
}

const DYNAMIC_ICON: Record<string, ReactElement> = {
  uncommitted: <Pen className="h-4 w-4" strokeWidth={1.75} />,
  staged: <CircleDot className="h-4 w-4" strokeWidth={1.75} />,
  'branch-fix': <Bug className="h-4 w-4" strokeWidth={1.75} />,
  'branch-feat': <Box className="h-4 w-4" strokeWidth={1.75} />,
  'branch-refactor': <GitBranch className="h-4 w-4" strokeWidth={1.75} />,
  todos: <ListTodo className="h-4 w-4" strokeWidth={1.75} />,
  understand: <FolderSearch className="h-4 w-4" strokeWidth={1.75} />
}

function iconForDynamic(id: string): ReactElement {
  for (const [prefix, icon] of Object.entries(DYNAMIC_ICON)) {
    if (id.startsWith(prefix)) return icon
  }
  return <Sparkles className="h-4 w-4" strokeWidth={1.75} />
}

const CAROUSEL_INTERVAL_MS = 30_000

type Props = {
  onSelectSuggestion?: (prompt: string) => void
}

export function TaskSuggestionHero({ onSelectSuggestion }: Props): ReactElement {
  const { t } = useTranslation('common')
  const [focusedIndex, setFocusedIndex] = useState(0)
  const [animating, setAnimating] = useState(false)
  const [dynamicSuggestions, setDynamicSuggestions] = useState<WorkspaceSuggestion[] | null>(null)
  const workspaceRoot = useChatStore((s) => s.workspaceRoot)

  // Fetch dynamic suggestions based on workspace
  useEffect(() => {
    if (!workspaceRoot) return
    let cancelled = false
    window.dsGui.getWorkspaceSuggestions(workspaceRoot).then((result) => {
      if (cancelled) return
      if (result.ok && result.suggestions && result.suggestions.length > 0) {
        setDynamicSuggestions(result.suggestions)
      }
    }).catch(() => { /* fallback to static */ })
    return () => { cancelled = true }
  }, [workspaceRoot])

  const itemCount = dynamicSuggestions ? dynamicSuggestions.length : STATIC_SUGGESTIONS.length

  const advanceFocus = useCallback(() => {
    setAnimating(true)
    setFocusedIndex((prev) => (prev + 1) % itemCount)
    window.setTimeout(() => setAnimating(false), 480)
  }, [itemCount])

  useEffect(() => {
    const timer = window.setInterval(advanceFocus, CAROUSEL_INTERVAL_MS)
    return () => window.clearInterval(timer)
  }, [advanceFocus])

  const scanPrompt = t('promptStructurePrompt')

  return (
    <div className="ds-no-drag w-full">
      <div className="ds-hero-panel ds-glass w-full rounded-[22px] px-5 py-7 sm:px-6 sm:py-8">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0 flex-1 text-left">
            <div className="mb-2 flex items-center gap-1.5 text-accent">
              <Sparkles className="h-4 w-4 shrink-0" strokeWidth={1.8} aria-hidden />
              <span className="text-[13px] font-semibold">{t('emptyHeroBadge')}</span>
            </div>
            <h1 className="text-[22px] font-semibold tracking-[-0.03em] text-ds-ink sm:text-[24px]">
              {t('emptyHeroTitle')}
            </h1>
            <p className="mt-2 max-w-[640px] text-[14px] leading-7 text-ds-muted">{t('emptyHeroSub')}</p>
          </div>
          <button
            type="button"
            onClick={() => onSelectSuggestion?.(scanPrompt)}
            className="inline-flex shrink-0 items-center gap-2 self-start rounded-full border border-ds-border bg-ds-elevated px-4 py-2 text-[13px] font-medium text-ds-ink transition hover:border-accent/25 hover:text-accent"
          >
            <ScanLine className="h-4 w-4" strokeWidth={1.8} />
            {t('emptyHeroScanProject')}
          </button>
        </div>

        <div
          className={`mt-6 grid grid-cols-1 gap-3 transition-opacity duration-500 sm:grid-cols-2 xl:grid-cols-4 ${
            animating ? 'opacity-[0.94]' : 'opacity-100'
          }`}
        >
          {dynamicSuggestions
            ? dynamicSuggestions.map((item, index) => {
                const focused = index === focusedIndex
                const isFirst = index === 0
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => onSelectSuggestion?.(item.prompt)}
                    onMouseEnter={() => setFocusedIndex(index)}
                    className={[
                      'group relative flex min-h-[168px] flex-col rounded-[16px] border px-3.5 py-5 text-left transition-all duration-300 ease-out',
                      isFirst
                        ? 'border-accent/20 bg-ds-elevated ring-1 ring-accent/10 dark:border-accent/25'
                        : focused
                          ? 'border-ds-border-strong bg-ds-elevated ring-1 ring-accent/12'
                          : 'border-ds-border bg-ds-card/80 hover:border-ds-border-strong hover:bg-ds-elevated'
                    ].join(' ')}
                  >
                    {isFirst ? (
                      <span className="absolute right-2.5 top-2.5 rounded-full bg-blue-500 px-2 py-0.5 text-[10px] font-semibold text-white">
                        {t('emptyHeroRecommended')}
                      </span>
                    ) : null}
                    <span
                      className={`mb-2.5 flex h-8 w-8 items-center justify-center rounded-[11px] ${ICON_TONE[item.tone]}`}
                    >
                      {iconForDynamic(item.id)}
                    </span>
                    <span className="text-[15px] font-semibold tracking-[-0.02em] text-ds-ink">
                      {item.title}
                    </span>
                    <span className="mt-1.5 line-clamp-2 text-[12.5px] leading-5 text-ds-muted">
                      {item.desc}
                    </span>
                  </button>
                )
              })
            : STATIC_SUGGESTIONS.map((item, index) => {
                const focused = index === focusedIndex
                const isRecommended = item.recommended === true
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => onSelectSuggestion?.(t(item.promptKey))}
                    onMouseEnter={() => setFocusedIndex(index)}
                    className={[
                      'group relative flex min-h-[168px] flex-col rounded-[16px] border px-3.5 py-5 text-left transition-all duration-300 ease-out',
                      isRecommended
                        ? 'border-accent/20 bg-ds-elevated ring-1 ring-accent/10 dark:border-accent/25'
                        : focused
                          ? 'border-ds-border-strong bg-ds-elevated ring-1 ring-accent/12'
                          : 'border-ds-border bg-ds-card/80 hover:border-ds-border-strong hover:bg-ds-elevated'
                    ].join(' ')}
                  >
                    {isRecommended ? (
                      <span className="absolute right-2.5 top-2.5 rounded-full bg-blue-500 px-2 py-0.5 text-[10px] font-semibold text-white">
                        {t('emptyHeroRecommended')}
                      </span>
                    ) : null}
                    <span
                      className={`mb-2.5 flex h-8 w-8 items-center justify-center rounded-[11px] ${ICON_TONE[item.tone]}`}
                    >
                      {item.icon}
                    </span>
                    <span className="text-[15px] font-semibold tracking-[-0.02em] text-ds-ink">
                      {t(item.titleKey)}
                    </span>
                    <span className="mt-1.5 line-clamp-2 text-[12.5px] leading-5 text-ds-muted">
                      {t(item.descKey)}
                    </span>
                    <span className="mt-1.5 line-clamp-1 text-[11px] text-ds-faint">{t(item.flowKey)}</span>
                    <span className={`mt-auto pt-2 text-[11px] font-medium ${TAG_TONE[item.tone]}`}>
                      {t(item.tagKey)}
                    </span>
                  </button>
                )
              })}
        </div>

        <div className="mt-4 flex items-center justify-center gap-1.5">
          {Array.from({ length: itemCount }).map((_, index) => (
            <button
              key={index}
              type="button"
              aria-label={`Suggestion ${index + 1}`}
              onClick={() => setFocusedIndex(index)}
              className={[
                'h-1 rounded-full transition-all duration-500',
                index === focusedIndex ? 'w-5 bg-accent' : 'w-1 bg-ds-border hover:bg-ds-muted'
              ].join(' ')}
            />
          ))}
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
