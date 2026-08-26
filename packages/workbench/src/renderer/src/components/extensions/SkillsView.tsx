import type { ReactElement } from 'react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import { useChatStore } from '../../store/chat-store'
import { InstalledSkillsPanel, type InstalledSkill } from './InstalledSkillsPanel'
import { SkillPreviewDialog } from './SkillPreviewDialog'
import { InstallSkillDialog } from './InstallSkillDialog'
import {
  loadInstalledPlugins,
  saveInstalledPlugins,
  storageKey,
  useNoticeAutoDismiss,
  type MarketplacePanelProps,
  type Notice
} from './marketplace-shared'
import { NoticeView } from './marketplace-ui'
import { MarketplaceBrowser, type InstallOutcome } from './MarketplaceBrowser'
import { ReloadHint } from './ReloadHint'
import { dedupeSkillsById, skillDiscoveryRoots, skillRootFromMdPath } from '@shared/skill-source'
import type { MarketplaceItem } from '../../../../shared/ds-gui-api'

export function SkillsView({
  query,
  createOpen,
  onCreateClose,
  createHost
}: MarketplacePanelProps): ReactElement {
  const { t } = useTranslation('common')
  const workspaceRoot = useChatStore((s) => s.workspaceRoot)
  const [installed, setInstalled] = useState<string[]>(() => loadInstalledPlugins())
  const [busyId, setBusyId] = useState<string | null>(null)
  const [notice, setNotice] = useState<Notice | null>(null)
  useNoticeAutoDismiss(notice, setNotice)
  const [skillsDir, setSkillsDir] = useState('~/.deepseek/skills')
  const [installedSkills, setInstalledSkills] = useState<InstalledSkill[]>([])
  const [skillsListLoading, setSkillsListLoading] = useState(false)
  const [previewSkill, setPreviewSkill] = useState<InstalledSkill | null>(null)
  // Bumped by the panel-header reload hint to force-refresh the ModelScope
  // market catalog in parallel with the local skills dir scan (one click
  // updates 内置 / 已安装 / 市场三个 tab).
  const [marketRefreshSignal, setMarketRefreshSignal] = useState(0)

  useEffect(() => {
    if (typeof window.dsGui?.getDeepseekPaths !== 'function') return
    void window.dsGui.getDeepseekPaths().then((paths) => setSkillsDir(paths.skillsDir))
  }, [])

  const refreshSkillsList = useCallback(async (): Promise<void> => {
    if (!skillsDir || typeof window.dsGui?.listSkillsInRoot !== 'function') return
    setSkillsListLoading(true)
    try {
      const roots = skillDiscoveryRoots(skillsDir, workspaceRoot)
      const results = await Promise.all(roots.map((root) => window.dsGui.listSkillsInRoot(root)))
      const byPath = new Map<string, InstalledSkill>()
      for (const result of results) {
        if (!result.ok) continue
        for (const skill of result.skills) {
          byPath.set(skill.path, skill)
        }
      }
      const merged = dedupeSkillsById([...byPath.values()]).sort((a, b) =>
        a.name.localeCompare(b.name)
      )
      setInstalledSkills(merged)
    } finally {
      setSkillsListLoading(false)
    }
  }, [skillsDir, workspaceRoot])

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

  const openSkill = async (skill: InstalledSkill): Promise<void> => {
    if (typeof window.dsGui?.openSkillRoot !== 'function') return
    const result = await window.dsGui.openSkillRoot(skillRootFromMdPath(skill.path))
    if (!result.ok) setNotice({ tone: 'error', message: result.message ?? t('pluginActionFailed') })
  }

  const deleteSkill = async (skill: InstalledSkill): Promise<void> => {
    if (skill.builtin || typeof window.dsGui?.deleteSkill !== 'function') return
    const copies = skill.copies && skill.copies.length > 0 ? skill.copies : [skill]
    const removable = copies.filter((copy) => !copy.builtin)
    if (removable.length === 0) return
    const confirmed =
      removable.length > 1
        ? window.confirm(t('skillDeleteConfirmCopies', { name: skill.name, count: removable.length }))
        : window.confirm(t('skillDeleteConfirm', { name: skill.name }))
    if (!confirmed) return
    setBusyId(skill.path)
    setNotice(null)
    try {
      let failed: string | null = null
      for (const copy of removable) {
        const result = await window.dsGui.deleteSkill(skillRootFromMdPath(copy.path), copy.id)
        if (!result.ok) {
          failed = result.message ?? t('pluginActionFailed')
          break
        }
      }
      if (failed) {
        setNotice({ tone: 'error', message: failed })
        await refreshSkillsList()
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
    <>
      {createHost
        ? createPortal(
            <InstallSkillDialog
              open={createOpen}
              skillsDir={skillsDir}
              onClose={onCreateClose}
              onInstalled={(path) => {
                void refreshSkillsList()
                setNotice({ tone: 'success', message: t('skillInstallSuccess', { path }) })
              }}
            />,
            createHost
          )
        : null}

      {notice ? <NoticeView notice={notice} /> : null}

      <div className="mt-6">
        <InstalledSkillsPanel
          skills={filteredSkills}
          loading={skillsListLoading}
          busyId={busyId}
          onPreview={(skill) => setPreviewSkill(skill)}
          onOpen={(skill) => void openSkill(skill)}
          onDelete={(skill) => void deleteSkill(skill)}
          headerRight={
            <ReloadHint
              onReload={async () => {
                setMarketRefreshSignal((n) => n + 1)
                await refreshSkillsList()
              }}
            />
          }
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

      <SkillPreviewDialog
        skillName={previewSkill?.id ?? null}
        skillsDir={previewSkill ? skillRootFromMdPath(previewSkill.path) : skillsDir}
        onClose={() => setPreviewSkill(null)}
      />
    </>
  )
}
