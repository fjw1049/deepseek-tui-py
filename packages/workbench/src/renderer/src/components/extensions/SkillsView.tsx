import type { ReactElement } from 'react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronDown, Loader2, Plus, Search, Settings } from 'lucide-react'
import { useChatStore } from '../../store/chat-store'
import { PluginsPanel, PluginsPanelHeader } from '../settings/PluginsPanel'
import {
  buildSkillContent,
  loadInstalledPlugins,
  normalizePluginId,
  saveInstalledPlugins,
  storageKey,
  type Notice
} from './marketplace-shared'
import { MarketplaceSection, NoticeView, type MarketplaceItem } from './marketplace-ui'

type SkillFilter = 'all' | 'recommended' | 'installed'

const RECOMMENDED_SKILLS: (MarketplaceItem & { skillInstructions: string })[] = [
  {
    id: 'code-review',
    kind: 'skill',
    titleKey: 'pluginSkillReviewTitle',
    descriptionKey: 'pluginSkillReviewDesc',
    skillInstructions:
      'Use this skill when reviewing a code change. Prioritize correctness, regressions, security, performance, and missing tests. Lead with concrete findings and file references.'
  },
  {
    id: 'frontend-polish',
    kind: 'skill',
    titleKey: 'pluginSkillFrontendTitle',
    descriptionKey: 'pluginSkillFrontendDesc',
    skillInstructions:
      'Use this skill when improving UI. Preserve the product style, check responsive states, avoid generic layouts, and verify the result visually before handing it back.'
  },
  {
    id: 'bug-hunt',
    kind: 'skill',
    titleKey: 'pluginSkillBugTitle',
    descriptionKey: 'pluginSkillBugDesc',
    skillInstructions:
      'Use this skill when investigating bugs. Reproduce or narrow the symptom, trace the data flow, identify the smallest fix, and add focused verification where possible.'
  },
  {
    id: 'release-notes',
    kind: 'skill',
    titleKey: 'pluginSkillReleaseTitle',
    descriptionKey: 'pluginSkillReleaseDesc',
    skillInstructions:
      'Use this skill when preparing release notes. Group user-facing changes by outcome, call out migrations or risks, and keep wording concise and scannable.'
  }
]

export function SkillsView(): ReactElement {
  const { t } = useTranslation('common')
  const { t: tSettings } = useTranslation('settings')
  const workspaceRoot = useChatStore((s) => s.workspaceRoot)
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<SkillFilter>('all')
  const [installed, setInstalled] = useState<string[]>(() => loadInstalledPlugins())
  const [busyId, setBusyId] = useState<string | null>(null)
  const [notice, setNotice] = useState<Notice | null>(null)
  const [customOpen, setCustomOpen] = useState(false)
  const [customName, setCustomName] = useState('')
  const [customDescription, setCustomDescription] = useState('')
  const [customBody, setCustomBody] = useState('')
  const [skillsDir, setSkillsDir] = useState('~/.deepseek/skills')
  const [installedSkills, setInstalledSkills] = useState<Array<{ id: string; name: string; path: string }>>([])
  const [skillsListLoading, setSkillsListLoading] = useState(false)

  // Silence unused var until per-workspace skill roots land here too.
  void workspaceRoot

  useEffect(() => {
    if (typeof window.dsGui?.getDeepseekPaths !== 'function') return
    void window.dsGui.getDeepseekPaths().then((paths) => setSkillsDir(paths.skillsDir))
  }, [])

  const refreshSkillsList = useCallback(async (): Promise<void> => {
    if (!skillsDir || typeof window.dsGui?.listSkillsInRoot !== 'function') return
    setSkillsListLoading(true)
    try {
      const result = await window.dsGui.listSkillsInRoot(skillsDir)
      setInstalledSkills(result.ok ? result.skills : [])
    } finally {
      setSkillsListLoading(false)
    }
  }, [skillsDir])

  useEffect(() => {
    void refreshSkillsList()
  }, [refreshSkillsList])

  const markInstalled = (key: string): void => {
    setInstalled((prev) => {
      const next = [...new Set([...prev, key])]
      saveInstalledPlugins(next)
      return next
    })
  }

  const isInstalled = useCallback(
    (item: Pick<MarketplaceItem, 'kind' | 'id'>): boolean => installed.includes(storageKey(item.kind, item.id)),
    [installed]
  )

  const visibleItems = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase()
    return RECOMMENDED_SKILLS.filter((item) => {
      const title = t(item.titleKey).toLowerCase()
      const description = t(item.descriptionKey).toLowerCase()
      return !normalizedQuery || title.includes(normalizedQuery) || description.includes(normalizedQuery)
    }).filter((item) => {
      if (filter === 'installed') return isInstalled(item)
      return true
    })
  }, [filter, isInstalled, query, t])

  const recommendedItems = visibleItems.filter((item) => !isInstalled(item))
  const personalItems = visibleItems.filter(isInstalled)

  const addItem = async (item: MarketplaceItem): Promise<void> => {
    setBusyId(storageKey(item.kind, item.id))
    setNotice(null)
    try {
      if (!skillsDir) {
        setNotice({ tone: 'error', message: t('pluginSkillRootMissing') })
        return
      }
      const recommended = RECOMMENDED_SKILLS.find((entry) => entry.id === item.id)
      const title = t(item.titleKey)
      const description = t(item.descriptionKey)
      const content = buildSkillContent(item.id, title, description, recommended?.skillInstructions ?? description)
      const result = await window.dsGui.saveSkillFile(skillsDir, item.id, content)
      if (!result.ok) {
        setNotice({ tone: 'error', message: result.message })
        return
      }
      markInstalled(storageKey('skill', item.id))
      await refreshSkillsList()
      setNotice({ tone: 'success', message: t('pluginSkillAdded', { path: result.path }) })
    } catch (e) {
      setNotice({ tone: 'error', message: e instanceof Error ? e.message : String(e) })
    } finally {
      setBusyId(null)
    }
  }

  const addCustom = async (): Promise<void> => {
    const id = normalizePluginId(customName)
    if (!id) {
      setNotice({ tone: 'error', message: t('pluginCustomNameRequired') })
      return
    }
    if (!skillsDir) {
      setNotice({ tone: 'error', message: t('pluginSkillRootMissing') })
      return
    }
    setBusyId('custom:skill')
    setNotice(null)
    try {
      const description = customDescription.trim() || t('pluginCustomFallbackDesc')
      const body = customBody.trim() || t('pluginCustomSkillFallbackBody')
      const content = buildSkillContent(id, customName.trim() || id, description, body)
      const result = await window.dsGui.saveSkillFile(skillsDir, id, content)
      if (!result.ok) {
        setNotice({ tone: 'error', message: result.message })
        return
      }
      markInstalled(storageKey('skill', id))
      await refreshSkillsList()
      setNotice({ tone: 'success', message: t('pluginSkillAdded', { path: result.path }) })
      setCustomName('')
      setCustomDescription('')
      setCustomBody('')
      setCustomOpen(false)
    } catch (e) {
      setNotice({ tone: 'error', message: e instanceof Error ? e.message : String(e) })
    } finally {
      setBusyId(null)
    }
  }

  const openSkillsDir = async (): Promise<void> => {
    if (!skillsDir || typeof window.dsGui?.openSkillRoot !== 'function') return
    const result = await window.dsGui.openSkillRoot(skillsDir)
    if (!result.ok) setNotice({ tone: 'error', message: result.message ?? t('pluginActionFailed') })
  }

  return (
    <div className="ds-feature-page ds-plugin-page ds-page-scroll ds-no-drag min-h-0 flex-1 overflow-y-auto px-6 py-7 md:px-10 lg:px-14">
      <div className="mx-auto max-w-6xl">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h1 className="text-[26px] font-semibold text-ds-ink md:text-[30px]">{t('extSkills')}</h1>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void openSkillsDir()}
              className="inline-flex items-center justify-center gap-2 rounded-xl bg-ds-subtle px-3 py-2 text-center text-[13px] font-semibold leading-none text-ds-ink transition hover:bg-ds-hover"
            >
              <Settings className="h-4 w-4" strokeWidth={1.75} />
              {t('pluginManage')}
            </button>
            <button
              type="button"
              onClick={() => setCustomOpen((value) => !value)}
              className="inline-flex items-center justify-center gap-2 rounded-xl bg-ds-userbubble px-3 py-2 text-center text-[13px] font-semibold leading-none text-ds-userbubbleFg shadow-sm transition hover:opacity-90"
            >
              <Plus className="h-4 w-4" strokeWidth={1.9} />
              {t('pluginCreate')}
            </button>
          </div>
        </div>

        <p className="mt-2 max-w-2xl text-[14px] leading-6 text-ds-muted">{t('pluginSkillTitle')}</p>

        <div className="ds-content-card mt-8 overflow-hidden rounded-2xl">
          <div className="border-b border-ds-border-muted px-5 py-4">
            <h2 className="text-[16px] font-semibold text-ds-ink">{tSettings('pluginsInstalled')}</h2>
            <PluginsPanelHeader />
          </div>
          <div className="px-5 py-5">
            <PluginsPanel
              showIntro={false}
              skillsDir={skillsDir}
              plugins={installedSkills}
              loading={skillsListLoading}
              onReload={() => void refreshSkillsList()}
              onOpenSkillsDir={() => void openSkillsDir()}
            />
          </div>
        </div>

        <div className="mt-9 flex flex-col gap-3 md:flex-row md:items-center">
          <label className="relative min-w-0 flex-1">
            <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-ds-faint" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              className="h-11 w-full rounded-2xl border border-ds-border bg-ds-card pl-11 pr-4 text-[15px] text-ds-ink shadow-sm outline-none transition focus:border-accent/40 focus:ring-1 focus:ring-accent/30"
              placeholder={t('pluginSearchSkill')}
            />
          </label>
          <label className="relative w-full md:w-[168px]">
            <select
              value={filter}
              onChange={(event) => setFilter(event.target.value as SkillFilter)}
              className="h-11 w-full appearance-none rounded-2xl border border-ds-border bg-ds-card px-4 pr-9 text-[15px] font-medium text-ds-ink shadow-sm outline-none transition focus:border-accent/40 focus:ring-1 focus:ring-accent/30"
            >
              <option value="all">{t('pluginFilterAll')}</option>
              <option value="installed">{t('pluginFilterInstalled')}</option>
            </select>
            <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ds-faint" />
          </label>
        </div>

        {customOpen ? (
          <section className="ds-content-card mt-6 rounded-2xl p-4">
            <div className="grid gap-3 md:grid-cols-2">
              <input
                value={customName}
                onChange={(event) => setCustomName(event.target.value)}
                className="h-10 rounded-xl border border-ds-border bg-ds-main/45 px-3 text-[14px] text-ds-ink outline-none focus:border-accent/40 focus:ring-1 focus:ring-accent/30"
                placeholder={t('pluginCustomName')}
              />
              <input
                value={customDescription}
                onChange={(event) => setCustomDescription(event.target.value)}
                className="h-10 rounded-xl border border-ds-border bg-ds-main/45 px-3 text-[14px] text-ds-ink outline-none focus:border-accent/40 focus:ring-1 focus:ring-accent/30"
                placeholder={t('pluginCustomDescription')}
              />
            </div>
            <textarea
              value={customBody}
              onChange={(event) => setCustomBody(event.target.value)}
              className="mt-3 min-h-[140px] w-full rounded-xl border border-ds-border bg-ds-main/45 px-3 py-2 font-mono text-[13px] leading-5 text-ds-ink outline-none focus:border-accent/40 focus:ring-1 focus:ring-accent/30"
              placeholder={t('pluginCustomSkillBody')}
              spellCheck={false}
            />
            <div className="mt-3 flex justify-end">
              <button
                type="button"
                onClick={() => void addCustom()}
                disabled={busyId === 'custom:skill'}
                className="inline-flex items-center justify-center gap-2 rounded-xl bg-ds-userbubble px-4 py-2 text-center text-[13px] font-semibold leading-none text-ds-userbubbleFg shadow-sm transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-55"
              >
                {busyId === 'custom:skill' ? (
                  <Loader2 className="h-4 w-4 animate-spin" strokeWidth={2} />
                ) : (
                  <Plus className="h-4 w-4" strokeWidth={2} />
                )}
                {t('pluginAddCustom')}
              </button>
            </div>
          </section>
        ) : null}

        {notice ? <NoticeView notice={notice} /> : null}

        <MarketplaceSection
          title={t('pluginRecommended')}
          emptyText={t('pluginNoResults')}
          items={recommendedItems}
          busyId={busyId}
          isInstalled={isInstalled}
          onAdd={addItem}
          t={t}
        />

        <MarketplaceSection
          title={t('pluginPersonal')}
          emptyText={t('pluginPersonalEmpty')}
          items={personalItems}
          busyId={busyId}
          isInstalled={isInstalled}
          onAdd={addItem}
          t={t}
        />
      </div>
    </div>
  )
}
