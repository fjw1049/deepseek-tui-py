import type { ReactElement } from 'react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Loader2, Plus, RefreshCw, Search } from 'lucide-react'
import { WORKBENCH_FEATURES } from '@shared/workbench-features'
import { useChatStore } from '../../store/chat-store'
import { useNoticeAutoDismiss, type Notice } from './marketplace-shared'
import { NoticeView } from './marketplace-ui'
import { ExtensionsToolbar } from './ExtensionsToolbar'
import {
  InstalledPluginsPanel,
  type MarketplaceInfo,
  type PluginRow,
  type RegistryEntry
} from './InstalledPluginsPanel'

/** Plugins are bundles of rules + skills + hooks + MCP servers managed by the
 * Python runtime (`/v1/plugins`). Mounting via “Use plugin” injects `rules/`
 * as scenario guidance; skills load on demand; hooks and MCP stay inactive
 * until the plugin is trusted. Mutations apply on the next session. */
export function PluginsView(): ReactElement {
  const { t } = useTranslation('common')
  const workspaceRoot = useChatStore((s) => s.workspaceRoot)
  const [query, setQuery] = useState('')
  const [plugins, setPlugins] = useState<PluginRow[]>([])
  const [loading, setLoading] = useState(false)
  /** Inline status in the panel header — avoids mounting a Notice that shifts the page. */
  const [reloadStatus, setReloadStatus] = useState<'idle' | 'loading' | 'done'>('idle')
  const [busyName, setBusyName] = useState<string | null>(null)
  const [notice, setNotice] = useState<Notice | null>(null)
  useNoticeAutoDismiss(notice, setNotice)

  useEffect(() => {
    if (reloadStatus !== 'done') return
    const timer = window.setTimeout(() => setReloadStatus('idle'), 1600)
    return () => window.clearTimeout(timer)
  }, [reloadStatus])
  const [installOpen, setInstallOpen] = useState(false)
  const installMenuRef = useRef<HTMLDivElement>(null)
  const [registry, setRegistry] = useState<RegistryEntry[] | null>(null)
  const [registryLoading, setRegistryLoading] = useState(false)
  const [registryError, setRegistryError] = useState(false)
  const [installingSource, setInstallingSource] = useState<string | null>(null)
  const [marketplaces, setMarketplaces] = useState<MarketplaceInfo[]>([])
  const [marketplacesLoading, setMarketplacesLoading] = useState(false)
  const [busyMarketplace, setBusyMarketplace] = useState<string | null>(null)

  useEffect(() => {
    if (!installOpen) return
    const handleClick = (event: MouseEvent): void => {
      if (installMenuRef.current && !installMenuRef.current.contains(event.target as Node)) {
        setInstallOpen(false)
      }
    }
    window.addEventListener('mousedown', handleClick)
    return () => window.removeEventListener('mousedown', handleClick)
  }, [installOpen])

  const refresh = useCallback(
    async (announce = false): Promise<void> => {
      if (typeof window.dsGui?.runtimeRequest !== 'function') return
      setLoading(true)
      if (announce) setReloadStatus('loading')
      try {
        const qs = workspaceRoot ? `?workspace=${encodeURIComponent(workspaceRoot)}` : ''
        const result = await window.dsGui.runtimeRequest(`/v1/plugins${qs}`, 'GET')
        if (!result.ok) {
          if (announce) setReloadStatus('idle')
          setNotice({ tone: 'error', message: extractApiError(result.body) || t('pluginActionFailed') })
          return
        }
        const parsed = JSON.parse(result.body) as { plugins?: PluginRow[] }
        setPlugins(parsed.plugins ?? [])
        if (announce) setReloadStatus('done')
      } catch (error) {
        if (announce) setReloadStatus('idle')
        setNotice({ tone: 'error', message: error instanceof Error ? error.message : String(error) })
      } finally {
        setLoading(false)
      }
    },
    [workspaceRoot, t]
  )

  useEffect(() => {
    void refresh()
  }, [refresh])

  const refreshMarketplaces = useCallback(async (): Promise<void> => {
    if (!WORKBENCH_FEATURES.pluginMarketplace) return
    if (typeof window.dsGui?.runtimeRequest !== 'function') return
    setMarketplacesLoading(true)
    try {
      const result = await window.dsGui.runtimeRequest('/v1/plugins/marketplaces', 'GET')
      if (!result.ok) return
      const parsed = JSON.parse(result.body) as { marketplaces?: MarketplaceInfo[] }
      setMarketplaces(parsed.marketplaces ?? [])
    } catch {
      /* marketplace listing is best-effort */
    } finally {
      setMarketplacesLoading(false)
    }
  }, [])

  useEffect(() => {
    void refreshMarketplaces()
  }, [refreshMarketplaces])

  useEffect(() => {
    if (!WORKBENCH_FEATURES.pluginMarketplace) return
    if (typeof window.dsGui?.runtimeRequest !== 'function') return
    let cancelled = false
    setRegistryLoading(true)
    window.dsGui
      .runtimeRequest('/v1/plugins/registry', 'GET')
      .then((result) => {
        if (cancelled) return
        if (!result.ok) {
          setRegistryError(true)
          return
        }
        const parsed = JSON.parse(result.body) as { plugins?: RegistryEntry[] }
        setRegistry(parsed.plugins ?? [])
      })
      .catch(() => {
        if (!cancelled) setRegistryError(true)
      })
      .finally(() => {
        if (!cancelled) setRegistryLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const mutate = useCallback(
    async (plugin: PluginRow, path: string, method: string, payload: Record<string, unknown>): Promise<void> => {
      if (typeof window.dsGui?.runtimeRequest !== 'function') return
      setBusyName(plugin.name)
      setNotice(null)
      try {
        const bodyPayload = {
          ...payload,
          scope: plugin.scope === 'project' ? 'project' : 'user',
          ...(plugin.scope === 'project' && workspaceRoot ? { workspace: workspaceRoot } : {})
        }
        const result = await window.dsGui.runtimeRequest(path, method, JSON.stringify(bodyPayload))
        if (!result.ok) {
          setNotice({ tone: 'error', message: extractApiError(result.body) || t('pluginActionFailed') })
          return
        }
        const parsed = JSON.parse(result.body) as { message?: string }
        setNotice({
          tone: 'success',
          message: `${parsed.message ?? t('pluginSysDone')} — ${t('pluginSysRestartHint')}`
        })
        await refresh()
      } catch (error) {
        setNotice({ tone: 'error', message: error instanceof Error ? error.message : String(error) })
      } finally {
        setBusyName(null)
      }
    },
    [refresh, t, workspaceRoot]
  )

  const handleTrust = useCallback(
    (plugin: PluginRow) => {
      if (!plugin.trusted) {
        const perms = plugin.permissions.length
          ? `\n\n${t('pluginSysPermissions')}: ${plugin.permissions.join(', ')}`
          : ''
        const ok = window.confirm(t('pluginSysTrustConfirm', { name: plugin.name }) + perms)
        if (!ok) return
      }
      void mutate(plugin, `/v1/plugins/${encodeURIComponent(plugin.name)}/action`, 'POST', {
        action: plugin.trusted ? 'untrust' : 'trust'
      })
    },
    [mutate, t]
  )

  const handleUpdate = useCallback(
    (plugin: PluginRow) => {
      void mutate(plugin, `/v1/plugins/${encodeURIComponent(plugin.name)}/action`, 'POST', {
        action: 'update'
      })
    },
    [mutate]
  )

  const handleRemove = useCallback(
    (plugin: PluginRow) => {
      const ok = window.confirm(t('pluginSysRemoveConfirm', { name: plugin.name }))
      if (!ok) return
      void mutate(plugin, `/v1/plugins/${encodeURIComponent(plugin.name)}`, 'DELETE', {})
    },
    [mutate, t]
  )

  const handleInstall = useCallback(
    async (spec: string, trust: boolean): Promise<boolean> => {
      if (typeof window.dsGui?.runtimeRequest !== 'function') return false
      setNotice(null)
      try {
        const result = await window.dsGui.runtimeRequest(
          '/v1/plugins/install',
          'POST',
          JSON.stringify({ spec, trust, scope: 'user' })
        )
        if (!result.ok) {
          setNotice({ tone: 'error', message: extractApiError(result.body) || t('pluginActionFailed') })
          return false
        }
        const parsed = JSON.parse(result.body) as { message?: string }
        setNotice({
          tone: 'success',
          message: `${parsed.message ?? t('pluginSysDone')} — ${t('pluginSysRestartHint')}`
        })
        await refresh()
        return true
      } catch (error) {
        setNotice({ tone: 'error', message: error instanceof Error ? error.message : String(error) })
        return false
      }
    },
    [refresh, t]
  )

  const handleMarketplaceInstall = useCallback(
    async (entry: RegistryEntry): Promise<void> => {
      setInstallingSource(entry.source)
      try {
        await handleInstall(entry.source, false)
      } finally {
        setInstallingSource(null)
      }
    },
    [handleInstall]
  )

  const handleMarketplaceAdd = useCallback(
    async (spec: string): Promise<boolean> => {
      if (typeof window.dsGui?.runtimeRequest !== 'function') return false
      setNotice(null)
      try {
        const result = await window.dsGui.runtimeRequest(
          '/v1/plugins/marketplaces',
          'POST',
          JSON.stringify({ spec })
        )
        if (!result.ok) {
          setNotice({ tone: 'error', message: extractApiError(result.body) || t('pluginActionFailed') })
          return false
        }
        const parsed = JSON.parse(result.body) as { message?: string }
        setNotice({ tone: 'success', message: parsed.message ?? t('pluginSysDone') })
        await refreshMarketplaces()
        return true
      } catch (error) {
        setNotice({ tone: 'error', message: error instanceof Error ? error.message : String(error) })
        return false
      }
    },
    [refreshMarketplaces, t]
  )

  const handleMarketplaceMutation = useCallback(
    async (name: string, path: string, method: string): Promise<void> => {
      if (typeof window.dsGui?.runtimeRequest !== 'function') return
      setBusyMarketplace(name)
      setNotice(null)
      try {
        const result = await window.dsGui.runtimeRequest(path, method)
        if (!result.ok) {
          setNotice({ tone: 'error', message: extractApiError(result.body) || t('pluginActionFailed') })
          return
        }
        const parsed = JSON.parse(result.body) as { message?: string }
        setNotice({ tone: 'success', message: parsed.message ?? t('pluginSysDone') })
        await refreshMarketplaces()
      } catch (error) {
        setNotice({ tone: 'error', message: error instanceof Error ? error.message : String(error) })
      } finally {
        setBusyMarketplace(null)
      }
    },
    [refreshMarketplaces, t]
  )

  const handleMarketplaceUpdate = useCallback(
    (name: string) => {
      void handleMarketplaceMutation(
        name,
        `/v1/plugins/marketplaces/${encodeURIComponent(name)}/update`,
        'POST'
      )
    },
    [handleMarketplaceMutation]
  )

  const handleMarketplaceRemove = useCallback(
    (name: string) => {
      const ok = window.confirm(t('pluginMpRemoveConfirm', { name }))
      if (!ok) return
      void handleMarketplaceMutation(
        name,
        `/v1/plugins/marketplaces/${encodeURIComponent(name)}`,
        'DELETE'
      )
    },
    [handleMarketplaceMutation, t]
  )

  const handleMarketplacePluginInstall = useCallback(
    async (spec: string): Promise<void> => {
      setInstallingSource(spec)
      try {
        await handleInstall(spec, false)
      } finally {
        setInstallingSource(null)
      }
    },
    [handleInstall]
  )

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return plugins
    return plugins.filter(
      (p) => p.name.toLowerCase().includes(q) || p.description.toLowerCase().includes(q)
    )
  }, [plugins, query])

  const installedNames = useMemo(() => new Set(plugins.map((p) => p.name.toLowerCase())), [plugins])

  const filteredRegistry = useMemo(() => {
    if (!registry) return []
    const q = query.trim().toLowerCase()
    if (!q) return registry
    return registry.filter(
      (e) => e.name.toLowerCase().includes(q) || e.description.toLowerCase().includes(q)
    )
  }, [registry, query])

  return (
    <div className="ds-feature-page ds-plugin-page ds-page-scroll ds-no-drag min-h-0 flex-1 overflow-y-auto px-8 py-8">
      <div className="mx-auto max-w-6xl">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h1 className="ds-ext-page-title text-[24px] font-semibold tracking-[-0.02em] text-ds-ink">{t('extPlugins')}</h1>
          <ExtensionsToolbar
            menuItems={[
              {
                label: t('connectorReload'),
                icon: <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} strokeWidth={1.75} />,
                onClick: () => void refresh(true),
                disabled: loading
              }
            ]}
          >
            <div className="relative" ref={installMenuRef}>
              <button
                type="button"
                onClick={() => setInstallOpen((open) => !open)}
                className="ds-ext-primary-action inline-flex items-center justify-center gap-2 rounded-xl bg-accent px-3 py-2 text-[13px] font-semibold leading-none text-white shadow-sm transition hover:brightness-110"
              >
                <Plus className="h-4 w-4" strokeWidth={1.9} />
                {t('pluginSysInstall')}
              </button>
              {installOpen ? (
                <InstallPluginPopover
                  onInstall={async (spec, trust) => {
                    const ok = await handleInstall(spec, trust)
                    if (ok) setInstallOpen(false)
                    return ok
                  }}
                />
              ) : null}
            </div>
          </ExtensionsToolbar>
        </div>
        <p className="mt-2 whitespace-nowrap text-[14px] leading-6 text-ds-muted">{t('pluginSysSubtitle')}</p>

        <label className="relative mt-6 block">
          <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-ds-faint" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t('pluginSysSearch')}
            className="ds-ext-search h-11 w-full rounded-2xl border border-ds-border bg-ds-card pl-11 pr-4 text-[15px] text-ds-ink shadow-sm outline-none transition focus:border-accent/40 focus:ring-1 focus:ring-accent/30"
          />
        </label>

        {notice ? <NoticeView notice={notice} /> : null}

        <div className="mt-6">
          <InstalledPluginsPanel
            plugins={filtered}
            loading={loading}
            busyName={busyName}
            marketplaceEnabled={WORKBENCH_FEATURES.pluginMarketplace}
            registry={registry}
            registryLoading={registryLoading}
            registryError={registryError}
            filteredRegistry={filteredRegistry}
            installedNames={installedNames}
            installingSource={installingSource}
            marketplaces={marketplaces}
            marketplacesLoading={marketplacesLoading}
            busyMarketplace={busyMarketplace}
            query={query}
            onTrust={handleTrust}
            onUpdate={handleUpdate}
            onRemove={handleRemove}
            onMarketplaceInstall={(entry) => void handleMarketplaceInstall(entry)}
            onMarketplaceAdd={handleMarketplaceAdd}
            onMarketplaceUpdate={handleMarketplaceUpdate}
            onMarketplaceRemove={handleMarketplaceRemove}
            onMarketplacePluginInstall={(spec) => void handleMarketplacePluginInstall(spec)}
            headerRight={
              <div className="flex h-5 min-w-[8.5rem] items-center justify-end gap-1.5 text-[12px]">
                {reloadStatus === 'loading' ? (
                  <>
                    <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-ds-muted" strokeWidth={2} />
                    <span className="truncate text-ds-muted">{t('skillsLoading')}</span>
                  </>
                ) : reloadStatus === 'done' ? (
                  <span className="truncate font-medium text-emerald-600 dark:text-emerald-400">
                    {t('listReloaded')}
                  </span>
                ) : (
                  <>
                    <RefreshCw className="h-3.5 w-3.5 shrink-0 text-ds-faint" strokeWidth={1.75} />
                    <span className="truncate text-ds-faint">{t('pluginSysRestartHint')}</span>
                  </>
                )}
              </div>
            }
          />
        </div>
      </div>
    </div>
  )
}

function extractApiError(body: string): string {
  try {
    const parsed = JSON.parse(body) as { detail?: { message?: string } | string; message?: string }
    if (typeof parsed.detail === 'string') return parsed.detail
    if (parsed.detail && typeof parsed.detail.message === 'string') return parsed.detail.message
    if (typeof parsed.message === 'string') return parsed.message
  } catch {
    /* fall through */
  }
  return body
}

function InstallPluginPopover({
  onInstall
}: {
  onInstall: (spec: string, trust: boolean) => Promise<boolean>
}): ReactElement {
  const { t } = useTranslation('common')
  const [spec, setSpec] = useState('')
  const [trust, setTrust] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  const submit = async (): Promise<void> => {
    const trimmed = spec.trim()
    if (!trimmed || submitting) return
    setSubmitting(true)
    try {
      await onInstall(trimmed, trust)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="ds-content-card absolute right-0 top-full z-20 mt-1.5 w-96 rounded-2xl p-4 shadow-lg">
      <h2 className="text-[14px] font-semibold text-ds-ink">{t('pluginSysInstallTitle')}</h2>
      <p className="mt-1 text-[12px] leading-5 text-ds-faint">{t('pluginSysInstallHint')}</p>
      <input
        value={spec}
        onChange={(event) => setSpec(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter') void submit()
        }}
        placeholder="github:owner/repo"
        autoFocus
        className="mt-3 h-10 w-full rounded-xl border border-ds-border bg-ds-main/45 px-3 font-mono text-[13px] text-ds-ink outline-none transition focus:border-accent/40 focus:ring-1 focus:ring-accent/30"
      />
      <label className="mt-3 flex cursor-pointer items-start gap-2">
        <input
          type="checkbox"
          checked={trust}
          onChange={(event) => setTrust(event.target.checked)}
          className="mt-0.5 h-4 w-4 accent-[var(--ds-accent)]"
        />
        <span className="text-[12px] leading-5 text-ds-muted">{t('pluginSysInstallTrust')}</span>
      </label>
      <button
        type="button"
        onClick={() => void submit()}
        disabled={!spec.trim() || submitting}
        className="ds-ext-primary-action mt-4 inline-flex w-full items-center justify-center gap-2 rounded-xl bg-accent px-3 py-2 text-[13px] font-semibold leading-none text-white shadow-sm transition hover:brightness-110 disabled:opacity-60"
      >
        {submitting ? <Loader2 className="h-4 w-4 animate-spin" strokeWidth={2} /> : null}
        {t('pluginSysInstall')}
      </button>
    </div>
  )
}
