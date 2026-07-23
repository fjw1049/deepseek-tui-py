import type { ReactElement } from 'react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Plus, RefreshCw, Search, Settings } from 'lucide-react'
import {
  listMcpServers,
  mergeMcpServerIntoConfig,
  mcpConfigHasServer,
  removeMcpServerFromConfig,
  setMcpServerEnabled,
  type McpServerEntry
} from '../../lib/mcp-json-merge'
import { reloadMcpWithRuntime } from '../../lib/settings-reload'
import { loadInstalledPlugins, saveInstalledPlugins, storageKey, useNoticeAutoDismiss, type Notice } from './marketplace-shared'
import { NoticeView } from './marketplace-ui'
import { InstalledConnectorsPanel, type ConnectorItem } from './InstalledConnectorsPanel'
import { MediaCatalogPanel } from './MediaCatalogPanel'
import { MEDIA_CATALOG } from './media-catalog'
import { MarketplaceBrowser, type InstallOutcome } from './MarketplaceBrowser'
import { AddMcpServerDialog } from './AddMcpServerDialog'
import { ImportMcpJsonDialog } from './ImportMcpJsonDialog'
import { resolveMcpInstall } from './modelscope-install'
import { ExtensionsToolbar } from './ExtensionsToolbar'
import type { MarketplaceItem } from '../../../../shared/ds-gui-api'

export function ConnectorsView(): ReactElement {
  const { t } = useTranslation('common')
  const { t: tSettings } = useTranslation('settings')
  const [query, setQuery] = useState('')
  const [installed, setInstalled] = useState<string[]>(() => loadInstalledPlugins())
  const [busyId, setBusyId] = useState<string | null>(null)
  const [notice, setNotice] = useState<Notice | null>(null)
  useNoticeAutoDismiss(notice, setNotice)
  const [menuOpen, setMenuOpen] = useState(false)
  const [addOpen, setAddOpen] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const [mcpConfigText, setMcpConfigText] = useState('')
  const [mcpLoaded, setMcpLoaded] = useState(false)
  const [reloading, setReloading] = useState(false)
  // Bumped by the top "重新加载" button to force-refresh the ModelScope market
  // catalog in parallel with the local mcp.json reload (single button updates
  // 内置 / 已安装 / 市场三个 tab).
  const [marketRefreshSignal, setMarketRefreshSignal] = useState(0)
  // Serialize mcp.json read-modify-write operations. Without this, concurrent
  // installs from the marketplace (different items, each calling appendMcpServer)
  // race: both read the same baseline, the second write overwrites the first,
  // and the first server silently disappears from config.
  const mcpWriteLockRef = useRef<Promise<unknown>>(Promise.resolve())
  const menuRef = useRef<HTMLDivElement>(null)

  // Close the create dropdown when clicking anywhere outside it.
  useEffect(() => {
    if (!menuOpen) return
    const handleClick = (event: MouseEvent): void => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setMenuOpen(false)
      }
    }
    window.addEventListener('mousedown', handleClick)
    return () => window.removeEventListener('mousedown', handleClick)
  }, [menuOpen])

  const withMcpWriteLock = useCallback(<T,>(task: () => Promise<T>): Promise<T> => {
    const run = mcpWriteLockRef.current.then(task, task)
    mcpWriteLockRef.current = run.then(
      () => undefined,
      () => undefined
    )
    return run
  }, [])

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
    // Bump the market catalog refresh signal alongside the local reload so the
    // single top button updates all three tabs (内置 / 已安装 / ModelScope 市场).
    setMarketRefreshSignal((n) => n + 1)
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

  // Connectors come solely from mcp.json servers.
  const connectors = useMemo<ConnectorItem[]>(() => {
    const titleById = new Map(MEDIA_CATALOG.map((item) => [item.id, item.title]))
    const userConnectors = listMcpServers(mcpConfigText).map((server) => ({
      id: server.id,
      name: titleById.get(server.id) ?? server.id,
      summary: server.summary,
      enabled: server.enabled,
      loadPolicy: server.loadPolicy,
      catalog: server.catalog
    }))
    const normalizedQuery = query.trim().toLowerCase()
    if (!normalizedQuery) return userConnectors
    return userConnectors.filter(
      (c) =>
        c.name.toLowerCase().includes(normalizedQuery) ||
        c.id.toLowerCase().includes(normalizedQuery) ||
        c.summary.toLowerCase().includes(normalizedQuery)
    )
  }, [mcpConfigText, query])

  const appendMcpServer = useCallback(
    async (id: string, entry: McpServerEntry): Promise<void> => {
      if (typeof window.dsGui?.setMcpConfigFile !== 'function') return
      await withMcpWriteLock(async () => {
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
        // Propagate the change to the running runtime so the new connector is
        // live immediately, without forcing the user to click 重新加载.
        void reloadMcpWithRuntime(readMcpConfig).catch(() => undefined)
      })
    },
    [mcpLoaded, mcpConfigText, readMcpConfig, t, withMcpWriteLock]
  )

  /** Upsert for media catalog (allows updating API key / re-enabling). */
  const upsertMcpServer = useCallback(
    async (id: string, entry: McpServerEntry): Promise<void> => {
      if (typeof window.dsGui?.setMcpConfigFile !== 'function') return
      setBusyId(id)
      setNotice(null)
      try {
        await withMcpWriteLock(async () => {
          const content = mcpLoaded ? mcpConfigText : await readMcpConfig()
          const next = mergeMcpServerIntoConfig(content, id, entry)
          const result = await window.dsGui.setMcpConfigFile(next)
          setMcpConfigText(next)
          setMcpLoaded(true)
          markInstalled(storageKey('mcp', id))
          setNotice({
            tone: 'success',
            message: t('mediaCatalogSaved', { name: id, path: result.path })
          })
          void reloadMcpWithRuntime(readMcpConfig).catch(() => undefined)
        })
      } catch (e) {
        setNotice({ tone: 'error', message: e instanceof Error ? e.message : String(e) })
      } finally {
        setBusyId(null)
      }
    },
    [mcpLoaded, mcpConfigText, readMcpConfig, t, withMcpWriteLock]
  )

  const deleteConnector = async (connector: ConnectorItem): Promise<void> => {
    if (typeof window.dsGui?.setMcpConfigFile !== 'function') return
    if (!window.confirm(t('connectorDeleteConfirm', { name: connector.name }))) return
    setBusyId(connector.id)
    setNotice(null)
    try {
      await withMcpWriteLock(async () => {
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
        void reloadMcpWithRuntime(readMcpConfig).catch(() => undefined)
      })
    } catch (e) {
      setNotice({ tone: 'error', message: e instanceof Error ? e.message : String(e) })
    } finally {
      setBusyId(null)
    }
  }

  const toggleConnector = async (connector: ConnectorItem, enabled: boolean): Promise<void> => {
    if (typeof window.dsGui?.setMcpConfigFile !== 'function') return
    setBusyId(connector.id)
    setNotice(null)
    try {
      await withMcpWriteLock(async () => {
        const content = mcpLoaded ? mcpConfigText : await readMcpConfig()
        const next = setMcpServerEnabled(content, connector.id, enabled)
        await window.dsGui.setMcpConfigFile(next)
        setMcpConfigText(next)
        void reloadMcpWithRuntime(readMcpConfig).catch(() => undefined)
      })
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

  const isDuplicate = useCallback(
    (id: string): boolean => mcpConfigHasServer(mcpConfigText, id),
    [mcpConfigText]
  )

  return (
    <div className="ds-feature-page ds-plugin-page ds-page-scroll ds-no-drag min-h-0 flex-1 overflow-y-auto px-8 py-8">
      <div className="mx-auto max-w-6xl">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h1 className="ds-ext-page-title text-[24px] font-semibold tracking-[-0.02em] text-ds-ink">{t('extConnectors')}</h1>
          <ExtensionsToolbar
            menuItems={[
              {
                label: t('connectorReload'),
                icon: <RefreshCw className={`h-3.5 w-3.5 ${reloading ? 'animate-spin' : ''}`} strokeWidth={1.75} />,
                onClick: () => void reloadMcp(),
                disabled: reloading
              },
              {
                label: t('pluginManage'),
                icon: <Settings className="h-3.5 w-3.5" strokeWidth={1.75} />,
                onClick: () => void openConfigDir()
              }
            ]}
          >
            <div className="relative" ref={menuRef}>
              <button
                type="button"
                onClick={() => setMenuOpen((value) => !value)}
                className="ds-ext-primary-action inline-flex items-center justify-center gap-2 rounded-xl bg-accent px-3 py-2 text-center text-[13px] font-semibold leading-none text-white shadow-sm transition hover:brightness-110"
              >
                <Plus className="h-4 w-4" strokeWidth={1.9} />
                {t('pluginCreate')}
              </button>
              {menuOpen ? (
                <div className="ds-content-card absolute right-0 top-full z-20 mt-1.5 w-52 overflow-hidden rounded-xl py-1 shadow-lg">
                  <button
                    type="button"
                    onClick={() => {
                      setMenuOpen(false)
                      setAddOpen(true)
                    }}
                    className="ds-ext-menu-item flex w-full items-center px-3.5 py-2 text-left text-[13px] text-ds-ink transition hover:bg-ds-subtle/60"
                  >
                    {t('connectorAddMcp')}
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setMenuOpen(false)
                      setImportOpen(true)
                    }}
                    className="ds-ext-menu-item flex w-full items-center px-3.5 py-2 text-left text-[13px] text-ds-ink transition hover:bg-ds-subtle/60"
                  >
                    {t('connectorImportJson')}
                  </button>
                </div>
              ) : null}
            </div>
          </ExtensionsToolbar>
        </div>

        <p className="mt-2 max-w-2xl text-[14px] leading-6 text-ds-muted">{t('connectorsIntro')}</p>

        <label className="relative mt-6 block">
          <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-ds-faint" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            className="ds-ext-search h-11 w-full rounded-2xl border border-ds-border bg-ds-card pl-11 pr-4 text-[15px] text-ds-ink shadow-sm outline-none transition focus:border-accent/40 focus:ring-1 focus:ring-accent/30"
            placeholder={t('connectorsSearch')}
          />
        </label>

        {notice ? <NoticeView notice={notice} /> : null}

        <div className="mt-6">
          <InstalledConnectorsPanel
            connectors={connectors}
            loading={!mcpLoaded}
            busyId={busyId}
            onToggle={(connector, enabled) => void toggleConnector(connector, enabled)}
            onDelete={(connector) => void deleteConnector(connector)}
            headerRight={
              <div className="flex min-w-0 items-center gap-1.5 text-[12px] text-ds-faint">
                <RefreshCw className="h-3.5 w-3.5 shrink-0" />
                <span className="truncate">{t('pluginMcpRestartHint')}</span>
              </div>
            }
            mediaSlot={
              <MediaCatalogPanel
                mcpConfigText={mcpConfigText}
                busyId={busyId}
                onConfigure={(id, entry) => upsertMcpServer(id, entry)}
                onToggle={(id, enabled) =>
                  void toggleConnector(
                    {
                      id,
                      name: id,
                      summary: '',
                      enabled: !enabled,
                      loadPolicy: 'on_focus',
                      catalog: 'media'
                    },
                    enabled
                  )
                }
              />
            }
            marketplaceSlot={
              <MarketplaceBrowser
                kind="mcp"
                query={query}
                isInstalled={isMarketplaceInstalled}
                onInstall={installFromMarketplace}
                refreshSignal={marketRefreshSignal}
              />
            }
          />
        </div>
      </div>

      <AddMcpServerDialog
        open={addOpen}
        onClose={() => setAddOpen(false)}
        isDuplicate={isDuplicate}
        onSubmit={appendMcpServer}
      />
      <ImportMcpJsonDialog
        open={importOpen}
        onClose={() => setImportOpen(false)}
        isDuplicate={isDuplicate}
        onSubmit={appendMcpServer}
      />
    </div>
  )
}
