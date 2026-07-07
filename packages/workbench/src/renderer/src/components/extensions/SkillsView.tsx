import type { ReactElement } from 'react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Loader2, Plus, RefreshCw, Search, Settings } from 'lucide-react'
import { useChatStore } from '../../store/chat-store'
import { InstalledSkillsPanel, type InstalledSkill } from './InstalledSkillsPanel'
import { SkillPreviewDialog } from './SkillPreviewDialog'
import {
  buildSkillContent,
  loadInstalledPlugins,
  normalizePluginId,
  saveInstalledPlugins,
  storageKey,
  type Notice
} from './marketplace-shared'
import { NoticeView } from './marketplace-ui'
import { MarketplaceBrowser, type InstallOutcome } from './MarketplaceBrowser'
import type { MarketplaceItem } from '../../../../shared/ds-gui-api'

export function SkillsView(): ReactElement {
  const { t } = useTranslation('common')
  const workspaceRoot = useChatStore((s) => s.workspaceRoot)
  const [query, setQuery] = useState('')
  const [installed, setInstalled] = useState<string[]>(() => loadInstalledPlugins())
  const [busyId, setBusyId] = useState<string | null>(null)
  const [notice, setNotice] = useState<Notice | null>(null)
  const [customOpen, setCustomOpen] = useState(false)
  const [customName, setCustomName] = useState('')
  const [customDescription, setCustomDescription] = useState('')
  const [customBody, setCustomBody] = useState('')
  const [skillsDir, setSkillsDir] = useState('~/.deepseek/skills')
  const [installedSkills, setInstalledSkills] = useState<InstalledSkill[]>([])
  const [skillsListLoading, setSkillsListLoading] = useState(false)
  const [previewSkill, setPreviewSkill] = useState<string | null>(null)
  // Bumped by the top "重新加载" button to force-refresh the ModelScope market
  // catalog in parallel with the local skills dir scan (single button updates
  // 内置 / 已安装 / 市场三个 tab).
  const [marketRefreshSignal, setMarketRefreshSignal] = useState(0)

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

  const isMarketplaceInstalled = useCallback(
    (item: MarketplaceItem): boolean =>
      installed.includes(storageKey('skill', item.id)) ||
      installedSkills.some((skill) => skill.id === item.id),
    [installed, installedSkills]
  )

  const installFromMarketplace = async (item: MarketplaceItem): Promise<InstallOutcome | null> => {
    if (!skillsDir || typeof window.dsGui?.saveSkillFile !== 'function') {
      return { tone: 'error', message: t('pluginSkillRootMissing') }
    }
    const fetched =
      typeof window.dsGui?.fetchSkillMarkdown === 'function'
        ? await window.dsGui.fetchSkillMarkdown(item.id)
        : { ok: false as const, sourceUrl: item.sourceUrl }
    if (!fetched.ok) {
      if (fetched.sourceUrl && typeof window.dsGui?.openExternal === 'function') {
        await window.dsGui.openExternal(fetched.sourceUrl)
      }
      return { tone: 'info', message: t('marketplaceSkillManual') }
    }
    // The GitHub SKILL.md already carries a complete frontmatter — write it as-is.
    const result = await window.dsGui.saveSkillFile(skillsDir, item.id, fetched.content)
    if (!result.ok) return { tone: 'error', message: result.message }
    markInstalled(storageKey('skill', item.id))
    await refreshSkillsList()
    return { tone: 'success', message: t('pluginSkillAdded', { path: result.path }) }
  }

  const filteredSkills = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase()
    if (!normalizedQuery) return installedSkills
    return installedSkills.filter(
      (skill) =>
        skill.name.toLowerCase().includes(normalizedQuery) ||
        skill.description.toLowerCase().includes(normalizedQuery)
    )
  }, [installedSkills, query])

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

  const deleteSkill = async (skill: InstalledSkill): Promise<void> => {
    if (skill.builtin || typeof window.dsGui?.deleteSkill !== 'function') return
    if (!window.confirm(t('skillDeleteConfirm', { name: skill.name }))) return
    setBusyId(skill.id)
    setNotice(null)
    try {
      const result = await window.dsGui.deleteSkill(skillsDir, skill.id)
      if (!result.ok) {
        setNotice({ tone: 'error', message: result.message ?? t('pluginActionFailed') })
        return
      }
      setInstalled((prev) => {
        const next = prev.filter((key) => key !== storageKey('skill', skill.id))
        saveInstalledPlugins(next)
        return next
      })
      await refreshSkillsList()
      setNotice({ tone: 'success', message: t('skillDeleted', { name: skill.name }) })
    } catch (e) {
      setNotice({ tone: 'error', message: e instanceof Error ? e.message : String(e) })
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="ds-feature-page ds-plugin-page ds-page-scroll ds-no-drag min-h-0 flex-1 overflow-y-auto px-6 py-7 md:px-10 lg:px-14">
      <div className="mx-auto max-w-6xl">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h1 className="text-[26px] font-semibold text-ds-ink md:text-[30px]">{t('extSkills')}</h1>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => {
                void refreshSkillsList()
                // Bump the market catalog refresh alongside the local scan so
                // the single top button updates all three tabs.
                setMarketRefreshSignal((n) => n + 1)
              }}
              disabled={skillsListLoading}
              className="inline-flex items-center justify-center gap-2 rounded-xl bg-ds-subtle px-3 py-2 text-center text-[13px] font-semibold leading-none text-ds-ink transition hover:bg-ds-hover disabled:opacity-60"
            >
              <RefreshCw className={`h-4 w-4 ${skillsListLoading ? 'animate-spin' : ''}`} strokeWidth={1.75} />
              {t('connectorReload')}
            </button>
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

        <label className="relative mt-6 block">
          <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-ds-faint" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            className="h-11 w-full rounded-2xl border border-ds-border bg-ds-card pl-11 pr-4 text-[15px] text-ds-ink shadow-sm outline-none transition focus:border-accent/40 focus:ring-1 focus:ring-accent/30"
            placeholder={t('pluginSearchSkill')}
          />
        </label>

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

        <div className="mt-6">
          <InstalledSkillsPanel
            skills={filteredSkills}
            loading={skillsListLoading}
            busyId={busyId}
            onPreview={(skill) => setPreviewSkill(skill.id)}
            onOpen={() => void openSkillsDir()}
            onDelete={(skill) => void deleteSkill(skill)}
            marketplaceSlot={
              <MarketplaceBrowser
                kind="skill"
                query={query}
                isInstalled={isMarketplaceInstalled}
                onInstall={installFromMarketplace}
                refreshSignal={marketRefreshSignal}
              />
            }
          />
        </div>
      </div>

      <SkillPreviewDialog skillName={previewSkill} skillsDir={skillsDir} onClose={() => setPreviewSkill(null)} />
    </div>
  )
}
