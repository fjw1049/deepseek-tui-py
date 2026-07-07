import type { ReactElement } from 'react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronDown, Loader2, Plus, RefreshCw, Search, Settings } from 'lucide-react'
import {
  buildMcpServerEntry,
  mergeMcpServerIntoConfig,
  mcpConfigHasServer,
  parseMcpConfigDocument,
  type McpServerEntry
} from '../../lib/mcp-json-merge'
import { normalizeWorkspaceRoot } from '../../lib/workspace-path'
import { reloadMcpWithRuntime } from '../../lib/settings-reload'
import { useChatStore } from '../../store/chat-store'
import { McpServersPanel } from '../settings/McpServersPanel'
import { loadInstalledPlugins, saveInstalledPlugins, storageKey, normalizePluginId, type Notice } from './marketplace-shared'
import { MarketplaceSection, NoticeView, type MarketplaceItem } from './marketplace-ui'

type ConnectorFilter = 'all' | 'installed'

/** Local connector presets — each is an MCP server the runtime spawns locally. */
const CONNECTOR_ITEMS: (MarketplaceItem & { install: (workspaceRoot: string) => McpServerEntry })[] = [
  {
    id: 'filesystem',
    kind: 'mcp',
    titleKey: 'pluginMcpFilesystemTitle',
    descriptionKey: 'pluginMcpFilesystemDesc',
    install: (workspaceRoot) =>
      buildMcpServerEntry('npx', ['-y', '@modelcontextprotocol/server-filesystem', workspaceRoot || '/path/to/project'])
  },
  {
    id: 'playwright',
    kind: 'mcp',
    titleKey: 'pluginMcpPlaywrightTitle',
    descriptionKey: 'pluginMcpPlaywrightDesc',
    install: () => buildMcpServerEntry('npx', ['-y', '@playwright/mcp@latest'])
  },
  {
    id: 'github',
    kind: 'mcp',
    titleKey: 'pluginMcpGithubTitle',
    descriptionKey: 'pluginMcpGithubDesc',
    install: () =>
      buildMcpServerEntry('npx', ['-y', '@modelcontextprotocol/server-github'], {
        GITHUB_PERSONAL_ACCESS_TOKEN: 'ghp_...'
      })
  },
  {
    id: 'context7',
    kind: 'mcp',
    titleKey: 'pluginMcpContext7Title',
    descriptionKey: 'pluginMcpContext7Desc',
    install: () => buildMcpServerEntry('npx', ['-y', '@upstash/context7-mcp@latest'])
  }
]

export function ConnectorsView(): ReactElement {
  const { t } = useTranslation('common')
  const { t: tSettings } = useTranslation('settings')
  const workspaceRoot = normalizeWorkspaceRoot(useChatStore((s) => s.workspaceRoot))
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<ConnectorFilter>('all')
  const [installed, setInstalled] = useState<string[]>(() => loadInstalledPlugins())
  const [busyId, setBusyId] = useState<string | null>(null)
  const [notice, setNotice] = useState<Notice | null>(null)
  const [customOpen, setCustomOpen] = useState(false)
  const [customName, setCustomName] = useState('')
  const [customCommand, setCustomCommand] = useState('')
  const [customArgs, setCustomArgs] = useState('')
  const [customConfig, setCustomConfig] = useState('')
  const [mcpConfigPath, setMcpConfigPath] = useState('~/.deepseek/mcp.json')
  const [mcpConfigText, setMcpConfigText] = useState('')
  const [mcpConfigExists, setMcpConfigExists] = useState(false)
  const [mcpLoaded, setMcpLoaded] = useState(false)
  const [mcpBusy, setMcpBusy] = useState(false)
  const [mcpNotice, setMcpNotice] = useState<Notice | null>(null)

  const readMcpConfig = useCallback(async (): Promise<string> => {
    if (typeof window.dsGui?.getMcpConfigFile !== 'function') return mcpConfigText
    const file = await window.dsGui.getMcpConfigFile()
    setMcpConfigPath(file.path)
    setMcpConfigText(file.content)
    setMcpConfigExists(file.exists)
    setMcpLoaded(true)
    return file.content
  }, [mcpConfigText])

  useEffect(() => {
    if (mcpLoaded) return
    void readMcpConfig().catch((e) => setNotice({ tone: 'error', message: e instanceof Error ? e.message : String(e) }))
  }, [mcpLoaded, readMcpConfig])

  const reloadMcp = async (): Promise<void> => {
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
      if (!quiet) setMcpNotice({ tone: 'success', message: tSettings('mcpSaved', { path: result.path }) })
    } catch (e) {
      setMcpNotice({ tone: 'error', message: e instanceof Error ? e.message : String(e) })
    } finally {
      setMcpBusy(false)
    }
  }

  const openConfigDir = async (): Promise<void> => {
    if (typeof window.dsGui?.openMcpConfigDir !== 'function') return
    const result = await window.dsGui.openMcpConfigDir()
    if (!result.ok) setNotice({ tone: 'error', message: result.message ?? t('pluginActionFailed') })
  }

  const markInstalled = (key: string): void => {
    setInstalled((prev) => {
      const next = [...new Set([...prev, key])]
      saveInstalledPlugins(next)
      return next
    })
  }

  const isInstalled = useCallback(
    (item: Pick<MarketplaceItem, 'kind' | 'id'>): boolean => {
      if (installed.includes(storageKey(item.kind, item.id))) return true
      return item.kind === 'mcp' && mcpConfigHasServer(mcpConfigText, item.id)
    },
    [installed, mcpConfigText]
  )

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

  const visibleItems = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase()
    return CONNECTOR_ITEMS.filter((item) => {
      const title = t(item.titleKey).toLowerCase()
      const description = t(item.descriptionKey).toLowerCase()
      return !normalizedQuery || title.includes(normalizedQuery) || description.includes(normalizedQuery)
    }).filter((item) => (filter === 'installed' ? isInstalled(item) : true))
  }, [filter, isInstalled, query, t])

  const recommendedItems = visibleItems.filter((item) => !isInstalled(item))
  const personalItems = visibleItems.filter(isInstalled)

  const addItem = async (item: MarketplaceItem): Promise<void> => {
    const preset = CONNECTOR_ITEMS.find((entry) => entry.id === item.id)
    if (!preset) return
    setBusyId(storageKey(item.kind, item.id))
    setNotice(null)
    try {
      await appendMcpServer(item.id, preset.install(workspaceRoot))
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
    setBusyId('custom:mcp')
    setNotice(null)
    try {
      const rawCustom = customConfig.trim()
      const argsFromForm = customArgs
        .split('\n')
        .map((arg) => arg.trim())
        .filter(Boolean)
      let entry: McpServerEntry
      if (rawCustom.startsWith('{')) {
        const parsed = parseMcpConfigDocument(rawCustom)
        const servers = (parsed.mcpServers ?? parsed.servers) as Record<string, McpServerEntry> | undefined
        entry =
          servers?.[id] ??
          (Object.values(servers ?? {})[0] as McpServerEntry | undefined) ??
          buildMcpServerEntry(customCommand.trim() || 'npx', argsFromForm)
      } else {
        entry = buildMcpServerEntry(customCommand.trim() || 'npx', argsFromForm)
      }
      await appendMcpServer(id, entry)
      setCustomName('')
      setCustomCommand('')
      setCustomArgs('')
      setCustomConfig('')
      setCustomOpen(false)
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
          <h1 className="text-[26px] font-semibold text-ds-ink md:text-[30px]">{t('extConnectors')}</h1>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void openConfigDir()}
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

        <p className="mt-2 max-w-2xl text-[14px] leading-6 text-ds-muted">{t('connectorsIntro')}</p>

        <div className="ds-content-card mt-8 rounded-2xl p-5">
          <h2 className="mb-4 text-[18px] font-semibold text-ds-ink">{t('connectorsInstalled')}</h2>
          <McpServersPanel
            configPath={mcpConfigPath}
            configText={mcpConfigText}
            configExists={mcpConfigExists}
            loading={!mcpLoaded}
            busy={mcpBusy}
            notice={mcpNotice}
            onConfigTextChange={setMcpConfigText}
            onReload={() => void reloadMcp()}
            onSave={(content, quiet) => void saveMcpConfig(content, quiet)}
            onOpenConfigFolder={() => void openConfigDir()}
          />
        </div>

        <div className="mt-9 flex flex-col gap-3 md:flex-row md:items-center">
          <label className="relative min-w-0 flex-1">
            <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-ds-faint" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              className="h-11 w-full rounded-2xl border border-ds-border bg-ds-card pl-11 pr-4 text-[15px] text-ds-ink shadow-sm outline-none transition focus:border-accent/40 focus:ring-1 focus:ring-accent/30"
              placeholder={t('connectorsSearch')}
            />
          </label>
          <label className="relative w-full md:w-[168px]">
            <select
              value={filter}
              onChange={(event) => setFilter(event.target.value as ConnectorFilter)}
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
                value={customCommand}
                onChange={(event) => setCustomCommand(event.target.value)}
                className="h-10 rounded-xl border border-ds-border bg-ds-main/45 px-3 text-[14px] text-ds-ink outline-none focus:border-accent/40 focus:ring-1 focus:ring-accent/30"
                placeholder={t('pluginCustomCommand')}
              />
            </div>
            <textarea
              value={customArgs}
              onChange={(event) => setCustomArgs(event.target.value)}
              className="mt-3 min-h-[80px] w-full rounded-xl border border-ds-border bg-ds-main/45 px-3 py-2 font-mono text-[13px] leading-5 text-ds-ink outline-none focus:border-accent/40 focus:ring-1 focus:ring-accent/30"
              placeholder={t('pluginCustomArgs')}
              spellCheck={false}
            />
            <textarea
              value={customConfig}
              onChange={(event) => setCustomConfig(event.target.value)}
              className="mt-3 min-h-[120px] w-full rounded-xl border border-ds-border bg-ds-main/45 px-3 py-2 font-mono text-[13px] leading-5 text-ds-ink outline-none focus:border-accent/40 focus:ring-1 focus:ring-accent/30"
              placeholder={t('pluginCustomMcpConfig')}
              spellCheck={false}
            />
            <div className="mt-3 flex justify-end">
              <button
                type="button"
                onClick={() => void addCustom()}
                disabled={busyId === 'custom:mcp'}
                className="inline-flex items-center justify-center gap-2 rounded-xl bg-ds-userbubble px-4 py-2 text-center text-[13px] font-semibold leading-none text-ds-userbubbleFg shadow-sm transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-55"
              >
                {busyId === 'custom:mcp' ? (
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

        <div className="mt-8 flex items-center gap-2 text-[12px] text-ds-faint">
          <RefreshCw className="h-3.5 w-3.5" />
          <span>{t('pluginMcpRestartHint')}</span>
        </div>
      </div>
    </div>
  )
}
