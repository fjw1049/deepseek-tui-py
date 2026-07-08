import type { MouseEvent as ReactMouseEvent, ReactElement } from 'react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Download,
  Loader2,
  Plus,
  Puzzle,
  RefreshCw,
  Search,
  Shield,
  ShieldCheck,
  Store,
  Trash2
} from 'lucide-react'
import { WORKBENCH_FEATURES } from '@shared/workbench-features'
import { useChatStore } from '../../store/chat-store'
import type { Notice } from './marketplace-shared'
import { NoticeView } from './marketplace-ui'

type PluginRow = {
  name: string
  version: string
  description: string
  path: string
  scope: string
  enabled: boolean
  trusted: boolean
  permissions: string[]
  components: { skills: boolean; hooks: boolean; mcp_servers: boolean }
}

type RegistryEntry = {
  name: string
  source: string
  description: string
  version: string
  components: string[]
  permissions: string[]
}

/** Plugins are bundles of skills + hooks + MCP servers managed by the Python
 * runtime (`/v1/plugins`). Skills load as-is; hooks and MCP servers stay
 * inactive until the plugin is trusted. Mutations apply on the next session. */
export function PluginsView(): ReactElement {
  const { t } = useTranslation('common')
  const workspaceRoot = useChatStore((s) => s.workspaceRoot)
  const [query, setQuery] = useState('')
  const [plugins, setPlugins] = useState<PluginRow[]>([])
  const [loading, setLoading] = useState(false)
  const [busyName, setBusyName] = useState<string | null>(null)
  const [notice, setNotice] = useState<Notice | null>(null)
  const [installOpen, setInstallOpen] = useState(false)
  const installMenuRef = useRef<HTMLDivElement>(null)
  const [registry, setRegistry] = useState<RegistryEntry[] | null>(null)
  const [registryLoading, setRegistryLoading] = useState(false)
  const [registryError, setRegistryError] = useState(false)
  const [installingSource, setInstallingSource] = useState<string | null>(null)

  // Close the install popover when clicking anywhere outside it.
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

  const refresh = useCallback(async (): Promise<void> => {
    if (typeof window.dsGui?.runtimeRequest !== 'function') return
    setLoading(true)
    try {
      const qs = workspaceRoot ? `?workspace=${encodeURIComponent(workspaceRoot)}` : ''
      const result = await window.dsGui.runtimeRequest(`/v1/plugins${qs}`, 'GET')
      if (!result.ok) {
        setNotice({ tone: 'error', message: extractApiError(result.body) || t('pluginActionFailed') })
        return
      }
      const parsed = JSON.parse(result.body) as { plugins?: PluginRow[] }
      setPlugins(parsed.plugins ?? [])
    } catch (error) {
      setNotice({ tone: 'error', message: error instanceof Error ? error.message : String(error) })
    } finally {
      setLoading(false)
    }
  }, [workspaceRoot, t])

  useEffect(() => {
    void refresh()
  }, [refresh])

  // Marketplace index is a best-effort remote fetch; failure hides the
  // section content behind a quiet hint instead of an error banner.
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

  const handleToggle = useCallback(
    (plugin: PluginRow, enabled: boolean) => {
      void mutate(plugin, `/v1/plugins/${encodeURIComponent(plugin.name)}/action`, 'POST', {
        action: enabled ? 'enable' : 'disable'
      })
    },
    [mutate]
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
          <h1 className="text-[24px] font-semibold text-ds-ink">{t('extPlugins')}</h1>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void refresh()}
              disabled={loading}
              className="inline-flex items-center justify-center gap-2 rounded-xl bg-ds-subtle px-3 py-2 text-[13px] font-semibold leading-none text-ds-ink transition hover:bg-ds-hover disabled:opacity-60"
            >
              <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} strokeWidth={1.75} />
              {t('connectorReload')}
            </button>
            <div className="relative" ref={installMenuRef}>
              <button
                type="button"
                onClick={() => setInstallOpen((open) => !open)}
                className="inline-flex items-center justify-center gap-2 rounded-xl bg-accent px-3 py-2 text-[13px] font-semibold leading-none text-white shadow-sm transition hover:opacity-90"
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
          </div>
        </div>
        <p className="mt-2 max-w-2xl text-[14px] leading-6 text-ds-muted">{t('pluginSysSubtitle')}</p>

        <label className="relative mt-6 block">
          <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-ds-faint" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t('pluginSysSearch')}
            className="h-11 w-full rounded-2xl border border-ds-border bg-ds-card pl-11 pr-4 text-[15px] text-ds-ink shadow-sm outline-none transition focus:border-accent/40 focus:ring-1 focus:ring-accent/30"
          />
        </label>

        {notice ? <NoticeView notice={notice} /> : null}

        <div className="ds-content-card mt-6 overflow-hidden rounded-2xl">
          <div className="flex items-center justify-between gap-4 border-b border-ds-border-muted px-5 py-3.5">
            <div className="flex items-center gap-1.5 text-[15px] font-semibold text-ds-ink">
              {t('skillTabInstalled')}
              <span className="inline-flex min-w-[18px] items-center justify-center rounded-full bg-ds-ink/10 px-1.5 text-[11px] font-semibold text-ds-ink">
                {plugins.length}
              </span>
            </div>
            <span className="text-[12px] text-ds-faint">{t('pluginSysRestartHint')}</span>
          </div>
          {loading && plugins.length === 0 ? (
            <div className="flex items-center gap-2 px-5 py-8 text-[13px] text-ds-muted">
              <Loader2 className="h-4 w-4 animate-spin" strokeWidth={2} />
              {t('skillsLoading')}
            </div>
          ) : filtered.length === 0 ? (
            <div className="px-5 py-10 text-center text-[13px] text-ds-faint">
              {plugins.length === 0 ? t('pluginSysEmpty') : t('pluginNoResults')}
            </div>
          ) : (
            <ul className="divide-y divide-ds-border-muted/70">
              {filtered.map((plugin) => (
                <PluginListRow
                  key={`${plugin.scope}:${plugin.name}`}
                  plugin={plugin}
                  busy={busyName === plugin.name}
                  onToggle={(enabled) => handleToggle(plugin, enabled)}
                  onTrust={() => handleTrust(plugin)}
                  onUpdate={() => handleUpdate(plugin)}
                  onRemove={() => handleRemove(plugin)}
                />
              ))}
            </ul>
          )}
        </div>

        {WORKBENCH_FEATURES.pluginMarketplace ? (
          <div className="ds-content-card mt-6 overflow-hidden rounded-2xl">
            <div className="flex items-center justify-between gap-4 border-b border-ds-border-muted px-5 py-3.5">
              <div className="flex items-center gap-1.5 text-[15px] font-semibold text-ds-ink">
                <Store className="h-4 w-4 text-ds-muted" strokeWidth={1.75} />
                {t('pluginSysMarketplace')}
                {registry ? (
                  <span className="inline-flex min-w-[18px] items-center justify-center rounded-full bg-ds-ink/10 px-1.5 text-[11px] font-semibold text-ds-ink">
                    {registry.length}
                  </span>
                ) : null}
              </div>
              <span className="text-[12px] text-ds-faint">{t('pluginSysMarketplaceHint')}</span>
            </div>
            {registryLoading ? (
              <div className="flex items-center gap-2 px-5 py-8 text-[13px] text-ds-muted">
                <Loader2 className="h-4 w-4 animate-spin" strokeWidth={2} />
                {t('skillsLoading')}
              </div>
            ) : registryError || registry === null ? (
              <div className="px-5 py-10 text-center text-[13px] text-ds-faint">
                {t('pluginSysMarketplaceUnavailable')}
              </div>
            ) : filteredRegistry.length === 0 ? (
              <div className="px-5 py-10 text-center text-[13px] text-ds-faint">
                {registry.length === 0 ? t('pluginSysMarketplaceEmpty') : t('pluginNoResults')}
              </div>
            ) : (
              <ul className="divide-y divide-ds-border-muted/70">
                {filteredRegistry.map((entry) => (
                  <MarketplaceRow
                    key={entry.source}
                    entry={entry}
                    installed={installedNames.has(entry.name.toLowerCase())}
                    installing={installingSource === entry.source}
                    onInstall={() => void handleMarketplaceInstall(entry)}
                  />
                ))}
              </ul>
            )}
          </div>
        ) : null}
      </div>
    </div>
  )
}

function MarketplaceRow({
  entry,
  installed,
  installing,
  onInstall
}: {
  entry: RegistryEntry
  installed: boolean
  installing: boolean
  onInstall: () => void
}): ReactElement {
  const { t } = useTranslation('common')
  return (
    <li className="flex items-center gap-4 px-5 py-4 transition hover:bg-ds-subtle/50">
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-ds-border bg-ds-card text-ds-muted">
        <Puzzle className="h-4.5 w-4.5" strokeWidth={1.6} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="truncate text-[15px] font-semibold text-ds-ink">{entry.name}</span>
          {entry.version ? (
            <span className="font-mono text-[11px] text-ds-faint">v{entry.version}</span>
          ) : null}
          <PermissionChips permissions={entry.permissions} />
        </div>
        <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5">
          {entry.description ? (
            <p className="line-clamp-1 text-[13px] leading-5 text-ds-muted" title={entry.description}>
              {entry.description}
            </p>
          ) : null}
          <span className="shrink-0 font-mono text-[11px] text-ds-faint">{entry.source}</span>
        </div>
      </div>
      <button
        type="button"
        onClick={onInstall}
        disabled={installed || installing}
        className="inline-flex shrink-0 items-center justify-center gap-1.5 rounded-lg bg-ds-subtle px-3 py-1.5 text-[12px] font-semibold text-ds-ink transition hover:bg-ds-hover disabled:opacity-50"
      >
        {installing ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={2} />
        ) : (
          <Download className="h-3.5 w-3.5" strokeWidth={1.75} />
        )}
        {installed ? t('pluginSysInstalled') : t('pluginSysInstall')}
      </button>
    </li>
  )
}

function PermissionChips({ permissions }: { permissions: string[] }): ReactElement | null {
  if (permissions.length === 0) return null
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      {permissions.map((perm) => (
        <span
          key={perm}
          className="inline-flex items-center rounded-full border border-ds-border-muted px-1.5 py-0.5 font-mono text-[10px] text-ds-faint"
        >
          {perm}
        </span>
      ))}
    </span>
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

function PluginListRow({
  plugin,
  busy,
  onToggle,
  onTrust,
  onUpdate,
  onRemove
}: {
  plugin: PluginRow
  busy: boolean
  onToggle: (enabled: boolean) => void
  onTrust: () => void
  onUpdate: () => void
  onRemove: () => void
}): ReactElement {
  const { t } = useTranslation('common')
  const hasExecutable = plugin.components.hooks || plugin.components.mcp_servers
  // Claude Code installs are surfaced read-only: enable/trust state lives in
  // our lockfile, but the files belong to Claude Code (no update/remove).
  const managedElsewhere = plugin.scope === 'claude'
  const stopRemove = (event: ReactMouseEvent): void => {
    event.stopPropagation()
    onRemove()
  }
  return (
    <li className={`group flex items-center gap-4 px-5 py-4 transition hover:bg-ds-subtle/50 ${plugin.enabled ? '' : 'opacity-60'}`}>
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-ds-border bg-ds-card text-ds-muted">
        <Puzzle className="h-4.5 w-4.5" strokeWidth={1.6} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="truncate text-[15px] font-semibold text-ds-ink">{plugin.name}</span>
          <span className="font-mono text-[11px] text-ds-faint">v{plugin.version}</span>
          <ScopeBadge scope={plugin.scope} />
          {hasExecutable ? (
            plugin.trusted ? (
              <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 text-[11px] font-semibold text-emerald-600 dark:text-emerald-400">
                <ShieldCheck className="h-3 w-3" strokeWidth={2} />
                {t('pluginSysTrusted')}
              </span>
            ) : (
              <span
                className="inline-flex items-center gap-1 rounded-full bg-amber-500/10 px-2 py-0.5 text-[11px] font-semibold text-amber-600 dark:text-amber-400"
                title={t('pluginSysUntrustedHint')}
              >
                <Shield className="h-3 w-3" strokeWidth={2} />
                {t('pluginSysUntrusted')}
              </span>
            )
          ) : null}
          <PermissionChips permissions={plugin.permissions} />
        </div>
        <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5">
          {plugin.description ? (
            <p className="line-clamp-1 text-[13px] leading-5 text-ds-muted" title={plugin.description}>
              {plugin.description}
            </p>
          ) : null}
          <span className="shrink-0 font-mono text-[11px] text-ds-faint">
            {[
              plugin.components.skills ? 'Skills' : null,
              plugin.components.hooks ? 'Hooks' : null,
              plugin.components.mcp_servers ? 'MCP' : null
            ]
              .filter(Boolean)
              .join(' · ')}
          </span>
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-1.5">
        {hasExecutable ? (
          <button
            type="button"
            onClick={onTrust}
            disabled={busy}
            title={plugin.trusted ? t('pluginSysUntrustAction') : t('pluginSysTrustAction')}
            aria-label={plugin.trusted ? t('pluginSysUntrustAction') : t('pluginSysTrustAction')}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-ds-muted opacity-0 transition hover:bg-ds-hover hover:text-ds-ink disabled:opacity-50 group-hover:opacity-100 focus-visible:opacity-100"
          >
            {plugin.trusted ? (
              <Shield className="h-4 w-4" strokeWidth={1.75} />
            ) : (
              <ShieldCheck className="h-4 w-4" strokeWidth={1.75} />
            )}
          </button>
        ) : null}
        {managedElsewhere ? null : (
          <>
            <button
              type="button"
              onClick={onUpdate}
              disabled={busy}
              title={t('pluginSysUpdateAction')}
              aria-label={t('pluginSysUpdateAction')}
              className="flex h-8 w-8 items-center justify-center rounded-lg text-ds-muted opacity-0 transition hover:bg-ds-hover hover:text-ds-ink disabled:opacity-50 group-hover:opacity-100 focus-visible:opacity-100"
            >
              <RefreshCw className="h-4 w-4" strokeWidth={1.75} />
            </button>
            <button
              type="button"
              onClick={stopRemove}
              disabled={busy}
              title={t('connectorDelete')}
              aria-label={t('connectorDelete')}
              className="flex h-8 w-8 items-center justify-center rounded-lg text-red-500 opacity-0 transition hover:bg-red-50 disabled:opacity-50 group-hover:opacity-100 focus-visible:opacity-100 dark:hover:bg-red-950/30"
            >
              {busy ? (
                <Loader2 className="h-4 w-4 animate-spin" strokeWidth={2} />
              ) : (
                <Trash2 className="h-4 w-4" strokeWidth={1.75} />
              )}
            </button>
          </>
        )}
        <PluginToggle checked={plugin.enabled} disabled={busy} onChange={onToggle} />
      </div>
    </li>
  )
}

function ScopeBadge({ scope }: { scope: string }): ReactElement {
  const { t } = useTranslation('common')
  const label =
    scope === 'project'
      ? t('pluginSysScopeProject')
      : scope === 'claude'
        ? t('pluginSysScopeClaude')
        : t('pluginSysScopeUser')
  return (
    <span className="inline-flex items-center rounded-full bg-ds-subtle px-2 py-0.5 text-[11px] font-semibold text-ds-muted">
      {label}
    </span>
  )
}

function PluginToggle({
  checked,
  disabled,
  onChange
}: {
  checked: boolean
  disabled?: boolean
  onChange: (enabled: boolean) => void
}): ReactElement {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative h-7 w-12 shrink-0 rounded-full transition disabled:cursor-not-allowed disabled:opacity-45 ${
        checked ? 'bg-emerald-500' : 'bg-ds-faint'
      }`}
    >
      <span
        className={`absolute top-0.5 h-6 w-6 rounded-full bg-white shadow transition ${
          checked ? 'left-6' : 'left-0.5'
        }`}
      />
    </button>
  )
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
        className="mt-4 inline-flex w-full items-center justify-center gap-2 rounded-xl bg-accent px-3 py-2 text-[13px] font-semibold leading-none text-white shadow-sm transition hover:opacity-90 disabled:opacity-60"
      >
        {submitting ? <Loader2 className="h-4 w-4 animate-spin" strokeWidth={2} /> : null}
        {t('pluginSysInstall')}
      </button>
    </div>
  )
}
