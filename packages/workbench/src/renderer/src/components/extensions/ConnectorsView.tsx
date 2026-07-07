import type { ReactElement } from 'react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Loader2, Plus, RefreshCw, Search, Settings } from 'lucide-react'
import {
  buildMcpServerEntry,
  listMcpServers,
  mergeMcpServerIntoConfig,
  mcpConfigHasServer,
  parseMcpConfigDocument,
  removeMcpServerFromConfig,
  setMcpServerEnabled,
  type McpServerEntry
} from '../../lib/mcp-json-merge'
import { reloadMcpWithRuntime } from '../../lib/settings-reload'
import { loadInstalledPlugins, saveInstalledPlugins, storageKey, normalizePluginId, type Notice } from './marketplace-shared'
import { NoticeView } from './marketplace-ui'
import { InstalledConnectorsPanel, type ConnectorItem } from './InstalledConnectorsPanel'
import { MarketplaceBrowser, type InstallOutcome } from './MarketplaceBrowser'
import { resolveMcpInstall } from './modelscope-install'
import type { MarketplaceItem } from '../../../../shared/ds-gui-api'

/** Hardcoded built-in connector shown in the 内置 tab (not backed by mcp.json). */
const BUILTIN_CONNECTORS: ConnectorItem[] = [
  {
    id: 'yahoo-finance',
    name: 'yahoo-finance',
    summary: 'Yahoo Finance — 行情、财报与市场数据',
    builtin: true,
    enabled: true
  }
]

export function ConnectorsView(): ReactElement {
  const { t } = useTranslation('common')
  const { t: tSettings } = useTranslation('settings')
  const [query, setQuery] = useState('')
  const [installed, setInstalled] = useState<string[]>(() => loadInstalledPlugins())
  const [busyId, setBusyId] = useState<string | null>(null)
  const [notice, setNotice] = useState<Notice | null>(null)
  const [customOpen, setCustomOpen] = useState(false)
  const [customName, setCustomName] = useState('')
  const [customCommand, setCustomCommand] = useState('')
  const [customArgs, setCustomArgs] = useState('')
  const [customConfig, setCustomConfig] = useState('')
  const [mcpConfigText, setMcpConfigText] = useState('')
  const [mcpLoaded, setMcpLoaded] = useState(false)
  const [reloading, setReloading] = useState(false)

  const readMcpConfig = useCallback(async (): Promise<string> => {
    if (typeof window.dsGui?.getMcpConfigFile !== 'function') return mcpConfigText
    const file = await window.dsGui.getMcpConfigFile()
    setMcpConfigText(file.content)
    setMcpLoaded(true)
    return file.content
  }, [mcpConfigText])

  useEffect(() => {
    if (mcpLoaded) return
    void readMcpConfig().catch((e) => setNotice({ tone: 'error', message: e instanceof Error ? e.message : String(e) }))
  }, [mcpLoaded, readMcpConfig])

  const reloadMcp = async (): Promise<void> => {
    setReloading(true)
    try {
      const result = await reloadMcpWithRuntime(readMcpConfig)
      setNotice({
        tone: result.runtime ? 'success' : 'info',
        message: result.runtime ? tSettings('mcpReloadRuntimeOk') : tSettings('mcpReloadDiskOnly')
      })
    } catch (e) {
      setNotice({ tone: 'error', message: e instanceof Error ? e.message : String(e) })
    } finally {
      setReloading(false)
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

  // Real connectors come from mcp.json servers; the built-in one is prepended.
  const connectors = useMemo<ConnectorItem[]>(() => {
    const userConnectors = listMcpServers(mcpConfigText).map((server) => ({
      id: server.id,
      name: server.id,
      summary: server.summary,
      builtin: false,
      enabled: server.enabled
    }))
    const normalizedQuery = query.trim().toLowerCase()
    const all = [...BUILTIN_CONNECTORS, ...userConnectors]
    if (!normalizedQuery) return all
    return all.filter(
      (c) => c.name.toLowerCase().includes(normalizedQuery) || c.summary.toLowerCase().includes(normalizedQuery)
    )
  }, [mcpConfigText, query])

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

  const deleteConnector = async (connector: ConnectorItem): Promise<void> => {
    if (connector.builtin || typeof window.dsGui?.setMcpConfigFile !== 'function') return
    if (!window.confirm(t('connectorDeleteConfirm', { name: connector.name }))) return
    setBusyId(connector.id)
    setNotice(null)
    try {
      const content = mcpLoaded ? mcpConfigText : await readMcpConfig()
      const next = removeMcpServerFromConfig(content, connector.id)
      const result = await window.dsGui.setMcpConfigFile(next)
      setMcpConfigText(next)
      setInstalled((prev) => {
        const filtered = prev.filter((key) => key !== storageKey('mcp', connector.id))
        saveInstalledPlugins(filtered)
        return filtered
      })
      setNotice({ tone: 'success', message: t('connectorDeleted', { name: connector.name, path: result.path }) })
    } catch (e) {
      setNotice({ tone: 'error', message: e instanceof Error ? e.message : String(e) })
    } finally {
      setBusyId(null)
    }
  }

  const toggleConnector = async (connector: ConnectorItem, enabled: boolean): Promise<void> => {
    if (connector.builtin || typeof window.dsGui?.setMcpConfigFile !== 'function') return
    setBusyId(connector.id)
    setNotice(null)
    try {
      const content = mcpLoaded ? mcpConfigText : await readMcpConfig()
      const next = setMcpServerEnabled(content, connector.id, enabled)
      await window.dsGui.setMcpConfigFile(next)
      setMcpConfigText(next)
    } catch (e) {
      setNotice({ tone: 'error', message: e instanceof Error ? e.message : String(e) })
    } finally {
      setBusyId(null)
    }
  }

  const isMarketplaceInstalled = useCallback(
    (item: MarketplaceItem): boolean =>
      installed.includes(storageKey('mcp', item.id)) || mcpConfigHasServer(mcpConfigText, item.id),
    [installed, mcpConfigText]
  )

  const installFromMarketplace = async (item: MarketplaceItem): Promise<InstallOutcome | null> => {
    const resolution = resolveMcpInstall(item)
    if (resolution.mode === 'manual') {
      if (item.sourceUrl && typeof window.dsGui?.openExternal === 'function') {
        await window.dsGui.openExternal(item.sourceUrl)
      }
      return { tone: 'info', message: t('marketplaceMcpManual') }
    }
    await appendMcpServer(item.id, resolution.entry)
    return null
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
              onClick={() => void reloadMcp()}
              disabled={reloading}
              className="inline-flex items-center justify-center gap-2 rounded-xl bg-ds-subtle px-3 py-2 text-center text-[13px] font-semibold leading-none text-ds-ink transition hover:bg-ds-hover disabled:opacity-60"
            >
              <RefreshCw className={`h-4 w-4 ${reloading ? 'animate-spin' : ''}`} strokeWidth={1.75} />
              {t('connectorReload')}
            </button>
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

        <label className="relative mt-6 block">
          <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-ds-faint" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            className="h-11 w-full rounded-2xl border border-ds-border bg-ds-card pl-11 pr-4 text-[15px] text-ds-ink shadow-sm outline-none transition focus:border-accent/40 focus:ring-1 focus:ring-accent/30"
            placeholder={t('connectorsSearch')}
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

        <div className="mt-6">
          <InstalledConnectorsPanel
            connectors={connectors}
            loading={!mcpLoaded}
            busyId={busyId}
            onToggle={(connector, enabled) => void toggleConnector(connector, enabled)}
            onDelete={(connector) => void deleteConnector(connector)}
          />
        </div>

        <MarketplaceBrowser
          kind="mcp"
          query={query}
          isInstalled={isMarketplaceInstalled}
          onInstall={installFromMarketplace}
        />

        <div className="mt-8 flex items-center gap-2 text-[12px] text-ds-faint">
          <RefreshCw className="h-3.5 w-3.5" />
          <span>{t('pluginMcpRestartHint')}</span>
        </div>
      </div>
    </div>
  )
}
