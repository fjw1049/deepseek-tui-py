import type { ReactElement } from 'react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Check,
  ChevronDown,
  Loader2,
  Plus,
  RefreshCw,
  Search,
  Settings
} from 'lucide-react'
import {
  buildMcpServerEntry,
  mergeMcpServerIntoConfig,
  mcpConfigHasServer,
  parseMcpConfigDocument,
  type McpServerEntry
} from '../lib/mcp-json-merge'
import { normalizeWorkspaceRoot } from '../lib/workspace-path'
import { useChatStore } from '../store/chat-store'
import { reloadMcpWithRuntime } from '../lib/settings-reload'
import { McpServersPanel } from './settings/McpServersPanel'
import { PluginsPanel } from './settings/PluginsPanel'

type PluginKind = 'mcp' | 'skill'
type PluginFilter = 'all' | 'recommended' | 'installed'
type NoticeTone = 'success' | 'error' | 'info'

type Notice = {
  tone: NoticeTone
  message: string
}

type MarketplaceItem = {
  id: string
  kind: PluginKind
  titleKey: string
  descriptionKey: string
  group: 'recommended'
  mcpInstall?: (workspaceRoot: string) => { id: string; entry: McpServerEntry }
  skillInstructions?: string
}

const INSTALLED_STORAGE_KEY = 'deepseekgui.installedPlugins'

function loadInstalledPlugins(): string[] {
  try {
    const raw = window.localStorage.getItem(INSTALLED_STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw) as unknown
    return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === 'string') : []
  } catch {
    return []
  }
}

function saveInstalledPlugins(ids: string[]): void {
  try {
    window.localStorage.setItem(INSTALLED_STORAGE_KEY, JSON.stringify([...new Set(ids)]))
  } catch {
    /* localStorage may be unavailable */
  }
}

function storageKey(kind: PluginKind, id: string): string {
  return `${kind}:${id}`
}

function normalizePluginId(raw: string): string {
  return raw
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, '-')
    .replace(/^-+|-+$/g, '')
}

function buildSkillContent(id: string, title: string, description: string, instructions: string): string {
  return [
    '---',
    `name: ${id}`,
    `description: ${description}`,
    '---',
    '',
    `# ${title}`,
    '',
    instructions
  ].join('\n')
}

function skillNameLooksValid(raw: string): boolean {
  const value = raw.trim()
  return !!value && value !== '.' && value !== '..' && !/[\\/]/.test(value)
}

const RECOMMENDED_ITEMS: MarketplaceItem[] = [
  {
    id: 'filesystem',
    kind: 'mcp',
    titleKey: 'pluginMcpFilesystemTitle',
    descriptionKey: 'pluginMcpFilesystemDesc',
    group: 'recommended',
    mcpInstall: (workspaceRoot) => ({
      id: 'filesystem',
      entry: buildMcpServerEntry('npx', [
        '-y',
        '@modelcontextprotocol/server-filesystem',
        workspaceRoot || '/path/to/project'
      ])
    })
  },
  {
    id: 'playwright',
    kind: 'mcp',
    titleKey: 'pluginMcpPlaywrightTitle',
    descriptionKey: 'pluginMcpPlaywrightDesc',
    group: 'recommended',
    mcpInstall: () => ({
      id: 'playwright',
      entry: buildMcpServerEntry('npx', ['-y', '@playwright/mcp@latest'])
    })
  },
  {
    id: 'github',
    kind: 'mcp',
    titleKey: 'pluginMcpGithubTitle',
    descriptionKey: 'pluginMcpGithubDesc',
    group: 'recommended',
    mcpInstall: () => ({
      id: 'github',
      entry: buildMcpServerEntry('npx', ['-y', '@modelcontextprotocol/server-github'], {
        GITHUB_PERSONAL_ACCESS_TOKEN: 'ghp_...'
      })
    })
  },
  {
    id: 'context7',
    kind: 'mcp',
    titleKey: 'pluginMcpContext7Title',
    descriptionKey: 'pluginMcpContext7Desc',
    group: 'recommended',
    mcpInstall: () => ({
      id: 'context7',
      entry: buildMcpServerEntry('npx', ['-y', '@upstash/context7-mcp@latest'])
    })
  },
  {
    id: 'code-review',
    kind: 'skill',
    titleKey: 'pluginSkillReviewTitle',
    descriptionKey: 'pluginSkillReviewDesc',
    group: 'recommended',
    skillInstructions:
      'Use this skill when reviewing a code change. Prioritize correctness, regressions, security, performance, and missing tests. Lead with concrete findings and file references.'
  },
  {
    id: 'frontend-polish',
    kind: 'skill',
    titleKey: 'pluginSkillFrontendTitle',
    descriptionKey: 'pluginSkillFrontendDesc',
    group: 'recommended',
    skillInstructions:
      'Use this skill when improving UI. Preserve the product style, check responsive states, avoid generic layouts, and verify the result visually before handing it back.'
  },
  {
    id: 'bug-hunt',
    kind: 'skill',
    titleKey: 'pluginSkillBugTitle',
    descriptionKey: 'pluginSkillBugDesc',
    group: 'recommended',
    skillInstructions:
      'Use this skill when investigating bugs. Reproduce or narrow the symptom, trace the data flow, identify the smallest fix, and add focused verification where possible.'
  },
  {
    id: 'release-notes',
    kind: 'skill',
    titleKey: 'pluginSkillReleaseTitle',
    descriptionKey: 'pluginSkillReleaseDesc',
    group: 'recommended',
    skillInstructions:
      'Use this skill when preparing release notes. Group user-facing changes by outcome, call out migrations or risks, and keep wording concise and scannable.'
  }
]

export function PluginMarketplaceView(): ReactElement {
  const { t } = useTranslation('common')
  const { t: tSettings } = useTranslation('settings')
  const workspaceRoot = normalizeWorkspaceRoot(useChatStore((s) => s.workspaceRoot))
  const [activeKind, setActiveKind] = useState<PluginKind>('mcp')
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<PluginFilter>('all')
  const [installed, setInstalled] = useState<string[]>(() => loadInstalledPlugins())
  const [busyId, setBusyId] = useState<string | null>(null)
  const [notice, setNotice] = useState<Notice | null>(null)
  const [customOpen, setCustomOpen] = useState(false)
  const [customName, setCustomName] = useState('')
  const [customDescription, setCustomDescription] = useState('')
  const [customCommand, setCustomCommand] = useState('')
  const [customArgs, setCustomArgs] = useState('')
  const [customConfig, setCustomConfig] = useState('')
  const [customSkillBody, setCustomSkillBody] = useState('')
  const [deepseekPaths, setDeepseekPaths] = useState({
    skillsDir: '~/.deepseek/skills'
  })
  const [mcpConfigPath, setMcpConfigPath] = useState('~/.deepseek/mcp.json')
  const [mcpConfigText, setMcpConfigText] = useState('')
  const [mcpConfigExists, setMcpConfigExists] = useState(false)
  const [mcpLoaded, setMcpLoaded] = useState(false)
  const [mcpBusy, setMcpBusy] = useState(false)
  const [mcpNotice, setMcpNotice] = useState<Notice | null>(null)
  const [installedSkills, setInstalledSkills] = useState<Array<{ id: string; name: string; path: string }>>([])
  const [skillsListLoading, setSkillsListLoading] = useState(false)

  useEffect(() => {
    if (typeof window.dsGui?.getDeepseekPaths !== 'function') return
    void window.dsGui.getDeepseekPaths().then((paths) => {
      setDeepseekPaths({ skillsDir: paths.skillsDir })
    })
  }, [])

  const readMcpConfig = useCallback(async (): Promise<string> => {
    if (typeof window.dsGui?.getMcpConfigFile !== 'function') return mcpConfigText
    const file = await window.dsGui.getMcpConfigFile()
    setMcpConfigPath(file.path)
    setMcpConfigText(file.content)
    setMcpConfigExists(file.exists)
    setMcpLoaded(true)
    return file.content
  }, [mcpConfigText])

  const reloadMcpFromMarketplace = async (): Promise<void> => {
    try {
      const result = await reloadMcpWithRuntime(readMcpConfig)
      setMcpNotice({
        tone: result.runtime ? 'success' : 'info',
        message: result.runtime ? tSettings('mcpReloadRuntimeOk') : tSettings('mcpReloadDiskOnly')
      })
    } catch (e) {
      setMcpNotice({ tone: 'error', message: e instanceof Error ? e.message : String(e) })
    }
  }

  const saveMcpConfig = async (content?: string, quiet = false): Promise<void> => {
    if (typeof window.dsGui?.setMcpConfigFile !== 'function') return
    const payload = content ?? mcpConfigText
    setMcpBusy(true)
    if (!quiet) setMcpNotice(null)
    try {
      const result = await window.dsGui.setMcpConfigFile(payload)
      setMcpConfigText(payload)
      setMcpConfigExists(true)
      if (!quiet) {
        setMcpNotice({ tone: 'success', message: tSettings('mcpSaved', { path: result.path }) })
      }
    } catch (e) {
      setMcpNotice({ tone: 'error', message: e instanceof Error ? e.message : String(e) })
    } finally {
      setMcpBusy(false)
    }
  }

  useEffect(() => {
    if (activeKind !== 'mcp' || mcpLoaded) return
    void readMcpConfig().catch((e) => {
      setNotice({ tone: 'error', message: e instanceof Error ? e.message : String(e) })
    })
  }, [activeKind, mcpLoaded, readMcpConfig])

  useEffect(() => {
    setNotice(null)
    setCustomOpen(false)
    setMcpNotice(null)
  }, [activeKind])

  const refreshSkillsList = useCallback(async (): Promise<void> => {
    const root = deepseekPaths.skillsDir
    if (!root || typeof window.dsGui?.listSkillsInRoot !== 'function') return
    setSkillsListLoading(true)
    try {
      const result = await window.dsGui.listSkillsInRoot(root)
      setInstalledSkills(result.ok ? result.skills : [])
    } finally {
      setSkillsListLoading(false)
    }
  }, [deepseekPaths.skillsDir])

  useEffect(() => {
    if (activeKind !== 'skill') return
    void refreshSkillsList()
  }, [activeKind, refreshSkillsList])

  const markInstalled = (key: string): void => {
    setInstalled((prev) => {
      const next = [...new Set([...prev, key])]
      saveInstalledPlugins(next)
      return next
    })
  }

  const isInstalled = useCallback((item: Pick<MarketplaceItem, 'kind' | 'id'>): boolean => {
    const key = storageKey(item.kind, item.id)
    if (installed.includes(key)) return true
    return item.kind === 'mcp' && mcpConfigHasServer(mcpConfigText, item.id)
  }, [installed, mcpConfigText])

  const visibleItems = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase()
    return RECOMMENDED_ITEMS.filter((item) => item.kind === activeKind)
      .filter((item) => {
        const title = t(item.titleKey).toLowerCase()
        const description = t(item.descriptionKey).toLowerCase()
        return !normalizedQuery || title.includes(normalizedQuery) || description.includes(normalizedQuery)
      })
      .filter((item) => {
        if (filter === 'recommended') return item.group === 'recommended'
        if (filter === 'installed') return isInstalled(item)
        return true
      })
  }, [activeKind, filter, isInstalled, query, t])

  const recommendedItems = visibleItems.filter((item) => !isInstalled(item))
  const personalItems = visibleItems.filter(isInstalled)

  const appendMcpServer = async (id: string, entry: McpServerEntry): Promise<void> => {
    if (typeof window.dsGui?.setMcpConfigFile !== 'function') return
    const content = mcpLoaded ? mcpConfigText : await readMcpConfig()
    if (mcpConfigHasServer(content, id)) {
      markInstalled(storageKey('mcp', id))
      setNotice({ tone: 'info', message: t('pluginAlreadyAdded') })
      return
    }
    const next = mergeMcpServerIntoConfig(content, id, entry)
    const result = await window.dsGui.setMcpConfigFile(next)
    setMcpConfigText(next)
    setMcpLoaded(true)
    markInstalled(storageKey('mcp', id))
    setNotice({ tone: 'success', message: t('pluginMcpAdded', { path: result.path }) })
  }

  const addItem = async (item: MarketplaceItem): Promise<void> => {
    setBusyId(storageKey(item.kind, item.id))
    setNotice(null)
    try {
      if (item.kind === 'mcp') {
        if (!item.mcpInstall) return
        const install = item.mcpInstall(workspaceRoot)
        await appendMcpServer(install.id, install.entry)
        return
      }

      const skillsDir = deepseekPaths.skillsDir
      if (!skillsDir) {
        setNotice({ tone: 'error', message: t('pluginSkillRootMissing') })
        return
      }
      const title = t(item.titleKey)
      const description = t(item.descriptionKey)
      const content = buildSkillContent(
        item.id,
        title,
        description,
        item.skillInstructions ?? description
      )
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
    const description = customDescription.trim() || t('pluginCustomFallbackDesc')
    setBusyId(`custom:${activeKind}`)
    setNotice(null)
    try {
      if (activeKind === 'mcp') {
        const rawCustom = customConfig.trim()
        let entry: McpServerEntry
        if (rawCustom.startsWith('{')) {
          const parsed = parseMcpConfigDocument(rawCustom)
          const servers = (parsed.mcpServers ?? parsed.servers) as Record<string, McpServerEntry> | undefined
          entry =
            servers?.[id] ??
            (Object.values(servers ?? {})[0] as McpServerEntry | undefined) ??
            buildMcpServerEntry(
              customCommand.trim() || 'npx',
              customArgs
                .split('\n')
                .map((arg) => arg.trim())
                .filter(Boolean)
            )
        } else {
          entry = buildMcpServerEntry(
            customCommand.trim() || 'npx',
            customArgs
              .split('\n')
              .map((arg) => arg.trim())
              .filter(Boolean)
          )
        }
        await appendMcpServer(id, entry)
      } else {
        const skillsDir = deepseekPaths.skillsDir
        if (!skillsDir) {
          setNotice({ tone: 'error', message: t('pluginSkillRootMissing') })
          return
        }
        const body = customSkillBody.trim() || t('pluginCustomSkillFallbackBody')
        const content = buildSkillContent(id, customName.trim() || id, description, body)
        const result = await window.dsGui.saveSkillFile(skillsDir, id, content)
        if (!result.ok) {
          setNotice({ tone: 'error', message: result.message })
          return
        }
        markInstalled(storageKey('skill', id))
        await refreshSkillsList()
        setNotice({ tone: 'success', message: t('pluginSkillAdded', { path: result.path }) })
      }
      setCustomName('')
      setCustomDescription('')
      setCustomCommand('')
      setCustomArgs('')
      setCustomConfig('')
      setCustomSkillBody('')
      setCustomOpen(false)
    } catch (e) {
      setNotice({ tone: 'error', message: e instanceof Error ? e.message : String(e) })
    } finally {
      setBusyId(null)
    }
  }

  const openManageTarget = async (): Promise<void> => {
    try {
      if (activeKind === 'mcp') {
        const result = await window.dsGui.openMcpConfigDir()
        if (!result.ok) setNotice({ tone: 'error', message: result.message ?? t('pluginActionFailed') })
        return
      }
      const skillsDir = deepseekPaths.skillsDir
      if (!skillsDir) {
        setNotice({ tone: 'error', message: t('pluginSkillRootMissing') })
        return
      }
      const result = await window.dsGui.openSkillRoot(skillsDir)
      if (!result.ok) setNotice({ tone: 'error', message: result.message ?? t('pluginActionFailed') })
    } catch (e) {
      setNotice({ tone: 'error', message: e instanceof Error ? e.message : String(e) })
    }
  }

  return (
    <div className="ds-no-drag h-full min-h-0 overflow-y-auto px-6 py-7 md:px-10 lg:px-14">
      <div className="mx-auto max-w-6xl">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="inline-flex rounded-xl bg-ds-subtle p-1">
            <TabButton active={activeKind === 'mcp'} onClick={() => setActiveKind('mcp')}>
              {t('pluginTabMcp')}
            </TabButton>
            <TabButton active={activeKind === 'skill'} tone="skill" onClick={() => setActiveKind('skill')}>
              {t('pluginTabSkill')}
            </TabButton>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void openManageTarget()}
              className="inline-flex items-center gap-2 rounded-xl bg-ds-subtle px-3 py-2 text-[13px] font-semibold text-ds-ink transition hover:bg-ds-hover"
            >
              <Settings className="h-4 w-4" strokeWidth={1.75} />
              {t('pluginManage')}
            </button>
            <button
              type="button"
              onClick={() => setCustomOpen((value) => !value)}
              className="inline-flex items-center gap-2 rounded-xl bg-ds-userbubble px-3 py-2 text-[13px] font-semibold text-ds-userbubbleFg shadow-sm transition hover:opacity-90"
            >
              <Plus className="h-4 w-4" strokeWidth={1.9} />
              {t('pluginCreate')}
            </button>
          </div>
        </div>

        {activeKind === 'mcp' ? (
          <div className="mt-8 rounded-2xl border border-ds-border bg-ds-card/80 p-5 shadow-sm">
            <h2 className="mb-4 text-[18px] font-semibold text-ds-ink">{tSettings('mcpInstalled')}</h2>
            <McpServersPanel
              configPath={mcpConfigPath}
              configText={mcpConfigText}
              configExists={mcpConfigExists}
              loading={!mcpLoaded && activeKind === 'mcp'}
              busy={mcpBusy}
              notice={mcpNotice}
              onConfigTextChange={setMcpConfigText}
              onReload={() => void reloadMcpFromMarketplace()}
              onSave={(content, quiet) => void saveMcpConfig(content, quiet)}
              onOpenConfigFolder={() => void openManageTarget()}
            />
          </div>
        ) : (
          <div className="mt-8 rounded-2xl border border-ds-border bg-ds-card/80 p-5 shadow-sm">
            <h2 className="mb-4 text-[18px] font-semibold text-ds-ink">{tSettings('pluginsInstalled')}</h2>
            <PluginsPanel
              skillsDir={deepseekPaths.skillsDir}
              plugins={installedSkills}
              loading={skillsListLoading}
              onReload={() => void refreshSkillsList()}
              onOpenSkillsDir={() => void openManageTarget()}
            />
          </div>
        )}

        <div className="mt-9 flex flex-col items-center text-center">
          <h1 className="text-[32px] font-semibold text-ds-ink md:text-[40px]">
            {activeKind === 'mcp' ? t('pluginMcpTitle') : t('pluginSkillTitle')}
          </h1>
        </div>

        <div className="mt-9 flex flex-col gap-3 md:flex-row md:items-center">
          <label className="relative min-w-0 flex-1">
            <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-ds-faint" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              className="h-11 w-full rounded-2xl border border-ds-border bg-ds-card pl-11 pr-4 text-[15px] text-ds-ink shadow-sm outline-none transition focus:border-accent/40 focus:ring-1 focus:ring-accent/30"
              placeholder={activeKind === 'mcp' ? t('pluginSearchMcp') : t('pluginSearchSkill')}
            />
          </label>
          <label className="relative w-full md:w-[168px]">
            <select
              value={filter}
              onChange={(event) => setFilter(event.target.value as PluginFilter)}
              className="h-11 w-full appearance-none rounded-2xl border border-ds-border bg-ds-card px-4 pr-9 text-[15px] font-medium text-ds-ink shadow-sm outline-none transition focus:border-accent/40 focus:ring-1 focus:ring-accent/30"
            >
              <option value="all">{t('pluginFilterAll')}</option>
              <option value="recommended">{t('pluginFilterRecommended')}</option>
              <option value="installed">{t('pluginFilterInstalled')}</option>
            </select>
            <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ds-faint" />
          </label>
        </div>

        {customOpen ? (
          <CustomPluginPanel
            activeKind={activeKind}
            customName={customName}
            customDescription={customDescription}
            customCommand={customCommand}
            customArgs={customArgs}
            customConfig={customConfig}
            customSkillBody={customSkillBody}
            busy={busyId === `custom:${activeKind}`}
            onNameChange={setCustomName}
            onDescriptionChange={setCustomDescription}
            onCommandChange={setCustomCommand}
            onArgsChange={setCustomArgs}
            onConfigChange={setCustomConfig}
            onSkillBodyChange={setCustomSkillBody}
            onAdd={() => void addCustom()}
          />
        ) : null}

        {notice ? <NoticeView notice={notice} /> : null}

        <PluginSection
          title={t('pluginRecommended')}
          emptyText={t('pluginNoResults')}
          items={recommendedItems}
          busyId={busyId}
          isInstalled={isInstalled}
          onAdd={addItem}
          t={t}
        />

        <PluginSection
          title={t('pluginPersonal')}
          emptyText={t('pluginPersonalEmpty')}
          items={personalItems}
          busyId={busyId}
          isInstalled={isInstalled}
          onAdd={addItem}
          t={t}
        />

        {activeKind === 'mcp' ? (
          <div className="mt-8 flex items-center gap-2 text-[12px] text-ds-faint">
            <RefreshCw className="h-3.5 w-3.5" />
            <span>{t('pluginMcpRestartHint')}</span>
          </div>
        ) : null}
      </div>
    </div>
  )
}

function TabButton({
  active,
  tone = 'default',
  onClick,
  children
}: {
  active: boolean
  tone?: 'default' | 'skill'
  onClick: () => void
  children: string
}): ReactElement {
  const activeClass =
    tone === 'skill'
      ? 'bg-ds-skill-soft text-ds-skill shadow-sm'
      : 'bg-ds-card text-ds-ink shadow-sm'

  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-lg px-4 py-2 text-[15px] font-semibold transition ${
        active ? activeClass : 'text-ds-muted hover:text-ds-ink'
      }`}
    >
      {children}
    </button>
  )
}

function PluginSection({
  title,
  emptyText,
  items,
  busyId,
  isInstalled,
  onAdd,
  t
}: {
  title: string
  emptyText: string
  items: MarketplaceItem[]
  busyId: string | null
  isInstalled: (item: Pick<MarketplaceItem, 'kind' | 'id'>) => boolean
  onAdd: (item: MarketplaceItem) => Promise<void>
  t: (key: string, values?: Record<string, unknown>) => string
}): ReactElement {
  return (
    <section className="mt-8">
      <h2 className="border-b border-ds-border-muted pb-3 text-[20px] font-semibold text-ds-ink">
        {title}
      </h2>
      {items.length === 0 ? (
        <div className="py-8 text-[14px] text-ds-faint">{emptyText}</div>
      ) : (
        <div className="grid gap-x-14 md:grid-cols-2">
          {items.map((item) => {
            const itemKey = storageKey(item.kind, item.id)
            const installed = isInstalled(item)
            const busy = busyId === itemKey
            return (
              <div
                key={itemKey}
                className="flex min-h-[92px] items-center gap-5 border-b border-ds-border-muted py-5"
              >
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[17px] font-semibold text-ds-ink">
                    {t(item.titleKey)}
                  </div>
                  <p className="mt-1 line-clamp-2 text-[14px] leading-5 text-ds-muted">
                    {t(item.descriptionKey)}
                  </p>
                </div>
                <button
                  type="button"
                  disabled={installed || busy}
                  onClick={() => void onAdd(item)}
                  title={installed ? t('pluginAdded') : t('pluginAdd')}
                  className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl transition ${
                    installed
                      ? 'text-ds-faint'
                      : 'bg-ds-subtle text-ds-ink hover:bg-ds-hover disabled:opacity-60'
                  }`}
                >
                  {busy ? (
                    <Loader2 className="h-4 w-4 animate-spin" strokeWidth={2} />
                  ) : installed ? (
                    <Check className="h-4 w-4" strokeWidth={2} />
                  ) : (
                    <Plus className="h-4 w-4" strokeWidth={2} />
                  )}
                </button>
              </div>
            )
          })}
        </div>
      )}
    </section>
  )
}

function CustomPluginPanel({
  activeKind,
  customName,
  customDescription,
  customCommand,
  customArgs,
  customConfig,
  customSkillBody,
  busy,
  onNameChange,
  onDescriptionChange,
  onCommandChange,
  onArgsChange,
  onConfigChange,
  onSkillBodyChange,
  onAdd
}: {
  activeKind: PluginKind
  customName: string
  customDescription: string
  customCommand: string
  customArgs: string
  customConfig: string
  customSkillBody: string
  busy: boolean
  onNameChange: (value: string) => void
  onDescriptionChange: (value: string) => void
  onCommandChange: (value: string) => void
  onArgsChange: (value: string) => void
  onConfigChange: (value: string) => void
  onSkillBodyChange: (value: string) => void
  onAdd: () => void
}): ReactElement {
  const { t } = useTranslation('common')
  return (
    <section className="mt-6 rounded-2xl border border-ds-border bg-ds-card/95 p-4 shadow-sm">
      <div className="grid gap-3 md:grid-cols-2">
        <input
          value={customName}
          onChange={(event) => onNameChange(event.target.value)}
          className="h-10 rounded-xl border border-ds-border bg-ds-main/45 px-3 text-[14px] text-ds-ink outline-none focus:border-accent/40 focus:ring-1 focus:ring-accent/30"
          placeholder={t('pluginCustomName')}
        />
        <input
          value={customDescription}
          onChange={(event) => onDescriptionChange(event.target.value)}
          className="h-10 rounded-xl border border-ds-border bg-ds-main/45 px-3 text-[14px] text-ds-ink outline-none focus:border-accent/40 focus:ring-1 focus:ring-accent/30"
          placeholder={t('pluginCustomDescription')}
        />
      </div>
      {activeKind === 'mcp' ? (
        <div className="mt-3 grid gap-3">
          <div className="grid gap-3 md:grid-cols-2">
            <input
              value={customCommand}
              onChange={(event) => onCommandChange(event.target.value)}
              className="h-10 rounded-xl border border-ds-border bg-ds-main/45 px-3 text-[14px] text-ds-ink outline-none focus:border-accent/40 focus:ring-1 focus:ring-accent/30"
              placeholder={t('pluginCustomCommand')}
            />
            <textarea
              value={customArgs}
              onChange={(event) => onArgsChange(event.target.value)}
              className="min-h-[80px] rounded-xl border border-ds-border bg-ds-main/45 px-3 py-2 font-mono text-[13px] leading-5 text-ds-ink outline-none focus:border-accent/40 focus:ring-1 focus:ring-accent/30"
              placeholder={t('pluginCustomArgs')}
              spellCheck={false}
            />
          </div>
          <textarea
            value={customConfig}
            onChange={(event) => onConfigChange(event.target.value)}
            className="min-h-[120px] rounded-xl border border-ds-border bg-ds-main/45 px-3 py-2 font-mono text-[13px] leading-5 text-ds-ink outline-none focus:border-accent/40 focus:ring-1 focus:ring-accent/30"
            placeholder={t('pluginCustomMcpConfig')}
            spellCheck={false}
          />
        </div>
      ) : (
        <textarea
          value={customSkillBody}
          onChange={(event) => onSkillBodyChange(event.target.value)}
          className="mt-3 min-h-[140px] w-full rounded-xl border border-ds-border bg-ds-main/45 px-3 py-2 font-mono text-[13px] leading-5 text-ds-ink outline-none focus:border-accent/40 focus:ring-1 focus:ring-accent/30"
          placeholder={t('pluginCustomSkillBody')}
          spellCheck={false}
        />
      )}
      <div className="mt-3 flex justify-end">
        <button
          type="button"
          onClick={onAdd}
          disabled={busy}
          className="inline-flex items-center gap-2 rounded-xl bg-ds-userbubble px-4 py-2 text-[13px] font-semibold text-ds-userbubbleFg shadow-sm transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-55"
        >
          {busy ? <Loader2 className="h-4 w-4 animate-spin" strokeWidth={2} /> : <Plus className="h-4 w-4" strokeWidth={2} />}
          {t('pluginAddCustom')}
        </button>
      </div>
    </section>
  )
}

function NoticeView({ notice }: { notice: Notice }): ReactElement {
  const className =
    notice.tone === 'error'
      ? 'border-red-300/80 bg-red-50 text-red-800 dark:border-red-800/70 dark:bg-red-950/25 dark:text-red-200'
      : notice.tone === 'success'
        ? 'border-emerald-300/80 bg-emerald-50 text-emerald-800 dark:border-emerald-800/70 dark:bg-emerald-950/25 dark:text-emerald-200'
        : 'border-ds-border bg-ds-subtle text-ds-muted'
  return (
    <div className={`mt-4 rounded-xl border px-3 py-2 text-[13px] leading-5 ${className}`}>
      {notice.message}
    </div>
  )
}
