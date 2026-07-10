import type { MouseEvent as ReactMouseEvent, ReactElement } from 'react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Download,
  Loader2,
  Puzzle,
  RefreshCw,
  Shield,
  ShieldCheck,
  Store,
  Trash2
} from 'lucide-react'
import { GlassSegmentedControl } from '../settings/GlassSegmentedControl'

export type PluginRow = {
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

export type RegistryEntry = {
  name: string
  source: string
  description: string
  version: string
  components: string[]
  permissions: string[]
}

type PluginTab = 'installed' | 'marketplace'

type Props = {
  plugins: PluginRow[]
  loading: boolean
  busyName: string | null
  marketplaceEnabled: boolean
  registry: RegistryEntry[] | null
  registryLoading: boolean
  registryError: boolean
  filteredRegistry: RegistryEntry[]
  installedNames: Set<string>
  installingSource: string | null
  onTrust: (plugin: PluginRow) => void
  onUpdate: (plugin: PluginRow) => void
  onRemove: (plugin: PluginRow) => void
  onMarketplaceInstall: (entry: RegistryEntry) => void
  headerRight?: ReactElement
}

export function InstalledPluginsPanel({
  plugins,
  loading,
  busyName,
  marketplaceEnabled,
  registry,
  registryLoading,
  registryError,
  filteredRegistry,
  installedNames,
  installingSource,
  onTrust,
  onUpdate,
  onRemove,
  onMarketplaceInstall,
  headerRight
}: Props): ReactElement {
  const { t } = useTranslation('common')
  const [tab, setTab] = useState<PluginTab>('installed')

  const tabItems: Array<{ value: PluginTab; label: string }> = [
    { value: 'installed', label: `${t('skillTabInstalled')} (${plugins.length})` },
    ...(marketplaceEnabled
      ? [{ value: 'marketplace' as const, label: t('pluginSysMarketplace') }]
      : [])
  ]

  return (
    <div className="ds-content-card overflow-hidden rounded-2xl">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-ds-border-muted px-5 py-3.5">
        {tabItems.length > 1 ? (
          <GlassSegmentedControl value={tab} onChange={setTab} items={tabItems} segmentClassName="px-3 py-1.5" />
        ) : (
          <div className="text-[15px] font-semibold text-ds-ink">
            {t('skillTabInstalled')}
            <span className="ml-1.5 inline-flex min-w-[18px] items-center justify-center rounded-full bg-ds-ink/10 px-1.5 text-[11px] font-semibold">
              {plugins.length}
            </span>
          </div>
        )}
        {headerRight ? <div className="min-w-0">{headerRight}</div> : null}
      </div>

      {tab === 'installed' ? (
        loading && plugins.length === 0 ? (
          <div className="flex items-center gap-2 px-5 py-8 text-[13px] text-ds-muted">
            <Loader2 className="h-4 w-4 animate-spin" strokeWidth={2} />
            {t('skillsLoading')}
          </div>
        ) : plugins.length === 0 ? (
          <div className="px-5 py-10 text-center text-[13px] text-ds-faint">{t('pluginSysEmpty')}</div>
        ) : (
          <ul className="divide-y divide-ds-border-muted/70">
            {plugins.map((plugin) => (
              <PluginListRow
                key={`${plugin.scope}:${plugin.name}`}
                plugin={plugin}
                busy={busyName === plugin.name}
                onTrust={() => onTrust(plugin)}
                onUpdate={() => onUpdate(plugin)}
                onRemove={() => onRemove(plugin)}
              />
            ))}
          </ul>
        )
      ) : marketplaceEnabled ? (
        <>
          <div className="flex items-center gap-1.5 border-b border-ds-border-muted/50 px-5 py-2.5 text-[12px] text-ds-faint">
            <Store className="h-3.5 w-3.5 shrink-0" strokeWidth={1.75} />
            <span>{t('pluginSysMarketplaceHint')}</span>
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
                  onInstall={() => onMarketplaceInstall(entry)}
                />
              ))}
            </ul>
          )}
        </>
      ) : null}
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
    <li className="group flex items-center gap-4 px-5 py-4 transition hover:bg-ds-subtle/50 active:bg-ds-subtle/70">
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
        className="ds-ext-row-action inline-flex shrink-0 items-center justify-center gap-1.5 rounded-lg bg-ds-subtle px-3 py-1.5 text-[12px] font-semibold text-ds-ink transition hover:bg-ds-hover disabled:opacity-50"
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

function PluginListRow({
  plugin,
  busy,
  onTrust,
  onUpdate,
  onRemove
}: {
  plugin: PluginRow
  busy: boolean
  onTrust: () => void
  onUpdate: () => void
  onRemove: () => void
}): ReactElement {
  const { t } = useTranslation('common')
  const hasExecutable = plugin.components.hooks || plugin.components.mcp_servers
  const managedElsewhere = plugin.scope === 'claude'
  const stopRemove = (event: ReactMouseEvent): void => {
    event.stopPropagation()
    onRemove()
  }
  return (
    <li className="group flex items-center gap-4 px-5 py-4 transition hover:bg-ds-subtle/50 active:bg-ds-subtle/70">
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
      <div className="flex shrink-0 items-center gap-1.5 opacity-40 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
        {hasExecutable ? (
          <button
            type="button"
            onClick={onTrust}
            disabled={busy}
            title={plugin.trusted ? t('pluginSysUntrustAction') : t('pluginSysTrustAction')}
            aria-label={plugin.trusted ? t('pluginSysUntrustAction') : t('pluginSysTrustAction')}
            className="ds-ext-row-action flex h-8 w-8 items-center justify-center rounded-lg text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink disabled:opacity-50"
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
              className="ds-ext-row-action flex h-8 w-8 items-center justify-center rounded-lg text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink disabled:opacity-50"
            >
              <RefreshCw className="h-4 w-4" strokeWidth={1.75} />
            </button>
            <button
              type="button"
              onClick={stopRemove}
              disabled={busy}
              title={t('connectorDelete')}
              aria-label={t('connectorDelete')}
              className="ds-ext-row-action flex h-8 w-8 items-center justify-center rounded-lg text-red-500 transition hover:bg-red-50 disabled:opacity-50 dark:hover:bg-red-950/30"
            >
              {busy ? (
                <Loader2 className="h-4 w-4 animate-spin" strokeWidth={2} />
              ) : (
                <Trash2 className="h-4 w-4" strokeWidth={1.75} />
              )}
            </button>
          </>
        )}
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
