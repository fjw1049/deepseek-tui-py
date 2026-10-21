import { usePluginNow } from './start-chat-with-plugin'
import { PluginDescription } from './PluginDescription'
import { PluginListItem } from './PluginListItem'
import { PluginIcon } from './PluginIcon'
import type { ReactElement } from 'react'
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import {
  Check,
  Download,
  Loader2,
  Plus,
  RefreshCw,
  Store,
  Trash2
} from 'lucide-react'
import { MarketplaceContentTabs } from './marketplace-ui'
import { PluginDialog } from './PluginDialog'
import {
  pluginDisplaySummary,
  pluginDisplayTitle,
} from './plugin-presentation'

export type PluginRow = {
  name: string
  version: string
  description: string
  path: string
  scope: string
  enabled: boolean
  trusted: boolean
  permissions: string[]
  components: {
    skills: boolean
    hooks: boolean
    mcp_servers: boolean
    commands: boolean
    agents: boolean
    rules: boolean
  }
}

export type RegistryEntry = {
  name: string
  source: string
  description: string
  version: string
  components: string[]
  permissions: string[]
}

export type MarketplacePluginEntry = {
  name: string
  description: string
  version: string
  category: string
  spec: string
}

export type MarketplaceInfo = {
  name: string
  source: string
  path: string
  plugins: MarketplacePluginEntry[]
}

type PluginTab = 'installed' | 'marketplace'

type DetailTarget =
  | { kind: 'installed'; key: string; plugin: PluginRow }
  | { kind: 'registry'; key: string; entry: RegistryEntry }
  | { kind: 'marketplace'; key: string; entry: MarketplacePluginEntry }

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
  marketplaces: MarketplaceInfo[]
  marketplacesLoading: boolean
  busyMarketplace: string | null
  query: string
  onRemove: (plugin: PluginRow) => void
  onTrust: (plugin: PluginRow) => void
  onUpdate: (plugin: PluginRow) => void
  onMarketplaceInstall: (entry: RegistryEntry) => void
  onMarketplaceAdd: (spec: string) => Promise<boolean>
  onMarketplaceUpdate: (name: string) => void
  onMarketplaceRemove: (name: string) => void
  onMarketplacePluginInstall: (spec: string) => void
  builtinPlugin?: ReactElement
  headerRight?: ReactElement
}

const CARD_CLASS =
  'group relative flex min-h-[200px] flex-col rounded-2xl border border-black/[0.04] bg-white p-4 shadow-[0_1px_2px_rgba(15,23,42,0.04)] transition hover:-translate-y-0.5 hover:shadow-[0_8px_24px_rgba(15,23,42,0.08)] dark:border-white/10 dark:bg-ds-card'

function pluginKey(plugin: PluginRow): string {
  return `${plugin.scope}:${plugin.name}`
}

function MetaChips({ items }: { items: string[] }): ReactElement | null {
  if (items.length === 0) return null
  return (
    <div className="mt-2.5 flex flex-wrap gap-1">
      {items.map((item) => (
        <span
          key={item}
          className="inline-flex items-center rounded-md bg-ds-subtle px-1.5 py-0.5 text-[11px] text-ds-muted"
        >
          {item}
        </span>
      ))}
    </div>
  )
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
  marketplaces,
  marketplacesLoading,
  busyMarketplace,
  query,
  onRemove,
  onTrust,
  onUpdate,
  onMarketplaceInstall,
  onMarketplaceAdd,
  onMarketplaceUpdate,
  onMarketplaceRemove,
  onMarketplacePluginInstall,
  headerRight,
  builtinPlugin
}: Props): ReactElement {
  const { t } = useTranslation('common')
  const [tab, setTab] = useState<PluginTab>('installed')
  const [detail, setDetail] = useState<DetailTarget | null>(null)

  const tabItems: Array<{ value: PluginTab; label: string }> = [
    { value: 'installed', label: t('skillTabInstalled') },
    ...(marketplaceEnabled
      ? [{ value: 'marketplace' as const, label: t('marketplaceTitle') }]
      : [])
  ]

  // Keep installed detail in sync when list refreshes / plugin removed.
  useEffect(() => {
    setDetail((prev) => {
      if (!prev || prev.kind !== 'installed') return prev
      const next = plugins.find((p) => pluginKey(p) === prev.key)
      if (!next) return null
      if (next === prev.plugin) return prev
      return { kind: 'installed', key: prev.key, plugin: next }
    })
  }, [plugins])

  const openInstalled = (plugin: PluginRow): void => {
    setDetail({ kind: 'installed', key: pluginKey(plugin), plugin })
  }

  return (
    <div className="min-w-0">
      {tabItems.length > 1 ? (
        <MarketplaceContentTabs value={tab} onChange={setTab} items={tabItems} trailing={headerRight} />
      ) : (
        <div className="flex items-center justify-between gap-3 px-3 pb-5 pt-3">
          <div className="text-[13px] font-medium text-ds-ink">{t('pluginCollectionTitle')} <span className="ml-2 text-ds-faint">{plugins.length + (builtinPlugin ? 1 : 0)}</span></div>
          {headerRight ? <div className="min-w-0">{headerRight}</div> : null}
        </div>
      )}

      {tab === 'installed' ? (
        <>
          <ul className="ds-plugin-grid">
            {builtinPlugin}
            {plugins.map((plugin) => (
              <PluginCard key={pluginKey(plugin)} plugin={plugin} busy={busyName === plugin.name} onRemove={() => onRemove(plugin)} onOpenDetails={() => openInstalled(plugin)} />
            ))}
          </ul>
          {loading ? <div role="status" className="flex items-center gap-2 px-3 py-8 text-sm text-ds-muted">
            <Loader2 className="size-4 animate-spin" />{t('skillsLoading')}
          </div> : !plugins.length && !builtinPlugin ? <p className="px-3 py-10 text-sm text-ds-muted">
            {t(query.trim() ? 'pluginNoResults' : 'pluginSysEmpty')}
          </p> : null}
        </>
      ) : marketplaceEnabled ? (
        <>
          <RegisteredMarketplacesSection
            marketplaces={marketplaces}
            loading={marketplacesLoading}
            busyMarketplace={busyMarketplace}
            query={query}
            installedNames={installedNames}
            installingSource={installingSource}
            onAdd={onMarketplaceAdd}
            onUpdate={onMarketplaceUpdate}
            onRemove={onMarketplaceRemove}
            onInstall={onMarketplacePluginInstall}
            onOpenDetails={(entry) =>
              setDetail({ kind: 'marketplace', key: entry.spec, entry })
            }
          />
          <div className="flex items-center gap-1.5 border-b border-t border-ds-border-muted/50 px-5 py-2.5 text-[12px] text-ds-faint">
            <Store className="h-3.5 w-3.5 shrink-0" strokeWidth={1.75} />
            <span>
              {t('pluginMpRegistryTitle')} — {t('pluginSysMarketplaceHint')}
            </span>
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
            <div className="bg-ds-subtle/40 px-4 py-4 dark:bg-ds-subtle/20 sm:px-5 sm:py-5">
              <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {filteredRegistry.map((entry) => (
                  <MarketplaceCard
                    key={entry.source}
                    entry={entry}
                    installed={installedNames.has(entry.name.toLowerCase())}
                    installing={installingSource === entry.source}
                    onInstall={() => onMarketplaceInstall(entry)}
                    onOpenDetails={() =>
                      setDetail({ kind: 'registry', key: entry.source, entry })
                    }
                  />
                ))}
              </ul>
            </div>
          )}
        </>
      ) : null}

      {detail
        ? createPortal(
            <PluginDetailDrawer
              detail={detail}
              busy={
                detail.kind === 'installed'
                  ? busyName === detail.plugin.name
                  : detail.kind === 'registry'
                    ? installingSource === detail.entry.source
                    : installingSource === detail.entry.spec
              }
              installed={
                detail.kind === 'installed'
                  ? true
                  : installedNames.has(
                      (detail.kind === 'registry' ? detail.entry.name : detail.entry.name).toLowerCase()
                    )
              }
              onClose={() => setDetail(null)}
              onTrust={detail.kind === 'installed' ? () => onTrust(detail.plugin) : undefined}
              onUpdate={detail.kind === 'installed' ? () => onUpdate(detail.plugin) : undefined}
              onInstall={
                detail.kind === 'registry'
                  ? () => onMarketplaceInstall(detail.entry)
                  : detail.kind === 'marketplace'
                    ? () => onMarketplacePluginInstall(detail.entry.spec)
                    : undefined
              }
            />,
            document.body
          )
        : null}
    </div>
  )
}

export function PluginDetailDrawer({ detail, busy, installed, onClose, onInstall, onTrust, onUpdate }: {
  detail: DetailTarget
  busy: boolean
  installed: boolean
  onClose: () => void
  onInstall?: () => void
  onTrust?: () => void
  onUpdate?: () => void
}): ReactElement {
  const { t, i18n } = useTranslation('common')
  const plugin = detail.kind === 'installed' ? detail.plugin : null
  const entry = detail.kind === 'installed' ? detail.plugin : detail.entry
  const permissions = detail.kind === 'installed' ? detail.plugin.permissions : detail.kind === 'registry' ? detail.entry.permissions : []
  const hasExecutable = plugin && (plugin.components.hooks || plugin.components.mcp_servers)
  const copyKey = { 'deep-research': 'pluginResearch', 'data-analysis': 'pluginData', 'document-process': 'pluginDocument' }[entry.name]
  const actionClass = 'rounded-lg border border-ds-border px-3 py-2 text-sm hover:bg-ds-hover disabled:opacity-50'
  return <PluginDialog pluginId={entry.name} title={pluginDisplayTitle(entry.name, i18n.language)}
    summary={pluginDisplaySummary(entry.name, i18n.language, entry.description)} onClose={onClose}>
    {copyKey ? <PluginDescription copyKey={copyKey} /> : null}
    {permissions.length > 0 ? <div className="mt-5 text-sm">
      <h3 className="font-medium">{t('pluginSysPermissions')}</h3>
      <p className="mt-2 break-words text-ds-muted">{permissions.join(' · ')}</p>
    </div> : null}
    {hasExecutable && !plugin?.trusted ? <p className="mt-4 text-sm leading-6 text-ds-muted">{t('pluginPermissionNotice')}</p> : null}
    <div className="mt-6 flex items-center justify-between border-t border-ds-border pt-4">
      <span className="text-xs text-ds-muted">{plugin ? t(plugin.enabled ? 'pluginDetailEnabledOn' : 'pluginDetailEnabledOff') : installed ? t('pluginSysInstalled') : ''}</span>
      {!plugin ? <button type="button" disabled={busy || installed} onClick={onInstall} className={actionClass}>{t(installed ? 'pluginSysInstalled' : 'pluginSysInstall')}</button> : <div className="flex gap-2">
        {hasExecutable && onTrust ? <button type="button" disabled={busy} onClick={onTrust} className={actionClass}>{t(plugin.trusted ? 'pluginSysUntrustAction' : 'pluginSysTrustAction')}</button> : null}
        {onUpdate && plugin.scope !== 'claude' && plugin.scope !== 'override' ? <button type="button" disabled={busy} onClick={onUpdate} className={actionClass}>{t('pluginSysUpdateAction')}</button> : null}
      </div>}
    </div>
  </PluginDialog>
}

function RegisteredMarketplacesSection({
  marketplaces,
  loading,
  busyMarketplace,
  query,
  installedNames,
  installingSource,
  onAdd,
  onUpdate,
  onRemove,
  onInstall,
  onOpenDetails
}: {
  marketplaces: MarketplaceInfo[]
  loading: boolean
  busyMarketplace: string | null
  query: string
  installedNames: Set<string>
  installingSource: string | null
  onAdd: (spec: string) => Promise<boolean>
  onUpdate: (name: string) => void
  onRemove: (name: string) => void
  onInstall: (spec: string) => void
  onOpenDetails: (entry: MarketplacePluginEntry) => void
}): ReactElement {
  const { t } = useTranslation('common')
  const [spec, setSpec] = useState('')
  const [adding, setAdding] = useState(false)

  const submit = async (): Promise<void> => {
    const trimmed = spec.trim()
    if (!trimmed || adding) return
    setAdding(true)
    try {
      const ok = await onAdd(trimmed)
      if (ok) setSpec('')
    } finally {
      setAdding(false)
    }
  }

  const q = query.trim().toLowerCase()

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-ds-border-muted/50 px-5 py-2.5">
        <div className="flex items-center gap-1.5 text-[12px] font-semibold text-ds-muted">
          <Store className="h-3.5 w-3.5 shrink-0" strokeWidth={1.75} />
          <span>{t('pluginMpSectionTitle')}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <input
            value={spec}
            onChange={(event) => setSpec(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') void submit()
            }}
            placeholder={t('pluginMpAddPlaceholder')}
            className="h-8 w-64 rounded-lg border border-ds-border bg-ds-main/45 px-2.5 font-mono text-[12px] text-ds-ink outline-none transition focus:border-accent/40 focus:ring-1 focus:ring-accent/30"
          />
          <button
            type="button"
            onClick={() => void submit()}
            disabled={!spec.trim() || adding}
            className="ds-ext-row-action inline-flex h-8 items-center justify-center gap-1.5 rounded-lg bg-ds-subtle px-2.5 text-[12px] font-semibold text-ds-ink transition hover:bg-ds-hover disabled:opacity-50"
          >
            {adding ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={2} />
            ) : (
              <Download className="h-3.5 w-3.5" strokeWidth={1.75} />
            )}
            {t('pluginMpAdd')}
          </button>
        </div>
      </div>
      {loading && marketplaces.length === 0 ? (
        <div className="flex items-center gap-2 px-5 py-6 text-[13px] text-ds-muted">
          <Loader2 className="h-4 w-4 animate-spin" strokeWidth={2} />
          {t('skillsLoading')}
        </div>
      ) : marketplaces.length === 0 ? (
        <div className="px-5 py-6 text-center text-[13px] text-ds-faint">{t('pluginMpEmpty')}</div>
      ) : (
        marketplaces.map((mp) => {
          const visible = q
            ? mp.plugins.filter(
                (p) =>
                  p.name.toLowerCase().includes(q) || p.description.toLowerCase().includes(q)
              )
            : mp.plugins
          const busy = busyMarketplace === mp.name
          return (
            <div key={mp.name}>
              <div className="flex items-center gap-2 border-b border-ds-border-muted/40 bg-ds-subtle/40 px-5 py-2">
                <span className="truncate text-[13px] font-semibold text-ds-ink">{mp.name}</span>
                <span className="truncate font-mono text-[11px] text-ds-faint">{mp.source}</span>
                <span className="shrink-0 text-[11px] text-ds-faint">
                  {t('pluginMpPluginCount', { count: mp.plugins.length })}
                </span>
                <span className="flex-1" />
                <button
                  type="button"
                  onClick={() => onUpdate(mp.name)}
                  disabled={busy}
                  title={t('pluginMpUpdateAction')}
                  aria-label={t('pluginMpUpdateAction')}
                  className="ds-ext-row-action flex h-7 w-7 items-center justify-center rounded-lg text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink disabled:opacity-50"
                >
                  {busy ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={2} />
                  ) : (
                    <RefreshCw className="h-3.5 w-3.5" strokeWidth={1.75} />
                  )}
                </button>
                <button
                  type="button"
                  onClick={() => onRemove(mp.name)}
                  disabled={busy}
                  title={t('pluginMpRemoveAction')}
                  aria-label={t('pluginMpRemoveAction')}
                  className="ds-ext-row-action flex h-7 w-7 items-center justify-center rounded-lg text-red-500 transition hover:bg-red-50 disabled:opacity-50 dark:hover:bg-red-950/30"
                >
                  <Trash2 className="h-3.5 w-3.5" strokeWidth={1.75} />
                </button>
              </div>
              {visible.length === 0 ? (
                <div className="px-5 py-4 text-center text-[12px] text-ds-faint">
                  {t('pluginNoResults')}
                </div>
              ) : (
                <div className="bg-ds-subtle/40 px-4 py-4 dark:bg-ds-subtle/20 sm:px-5">
                  <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
                    {visible.map((entry) => (
                      <MarketplacePluginCard
                        key={entry.spec}
                        entry={entry}
                        installed={installedNames.has(entry.name.toLowerCase())}
                        installing={installingSource === entry.spec}
                        onInstall={() => onInstall(entry.spec)}
                        onOpenDetails={() => onOpenDetails(entry)}
                      />
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )
        })
      )}
    </div>
  )
}

function MarketplacePluginCard({
  entry,
  installed,
  installing,
  onInstall,
  onOpenDetails
}: {
  entry: MarketplacePluginEntry
  installed: boolean
  installing: boolean
  onInstall: () => void
  onOpenDetails: () => void
}): ReactElement {
  const { t, i18n } = useTranslation('common')
  const title = pluginDisplayTitle(entry.name, i18n.language)
  const summary = pluginDisplaySummary(entry.name, i18n.language, entry.description)
  const actionLabel = installed ? t('pluginSysInstalled') : t('pluginSysInstall')
  const chips = [entry.category, entry.version ? `v${entry.version}` : null].filter(
    (v): v is string => Boolean(v)
  )
  return (
    <li className={CARD_CLASS}>
      <div className="flex min-h-0 flex-1 items-start gap-3">
        <PluginIcon pluginId={entry.name} />
        <div className="min-w-0 flex-1">
          <button type="button" onClick={onOpenDetails} className="min-w-0 text-left">
            <h3 className="truncate text-[15px] font-semibold tracking-[-0.01em] text-ds-ink hover:text-accent">
              {title}
            </h3>
          </button>
          <div className="mt-0.5 truncate font-mono text-[12px] text-ds-faint">{entry.name}</div>
          <p
            className="mt-2 line-clamp-3 overflow-hidden text-[13px] leading-5 text-ds-muted"
            title={summary}
          >
            {summary || entry.spec}
          </p>
          <MetaChips items={chips} />
        </div>
      </div>
      <div className="mt-auto flex items-center gap-2 border-t border-ds-border-muted pt-3.5">
        <span className="flex min-w-0 flex-1 items-center gap-1.5 text-[13px] text-ds-faint">
          <Download className="h-3.5 w-3.5 shrink-0" strokeWidth={1.75} />
          <span className="truncate font-mono" title={entry.spec}>
            {entry.spec}
          </span>
        </span>
        <button
          type="button"
          onClick={onOpenDetails}
          className="shrink-0 rounded-md border border-ds-border px-2 py-1 text-[12px] text-ds-muted hover:bg-ds-hover hover:text-ds-ink"
        >
          {t('pluginDetailsAction')}
        </button>
        <button
          type="button"
          onClick={onInstall}
          disabled={installed || installing}
          title={actionLabel}
          aria-label={actionLabel}
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-ds-muted transition hover:bg-ds-subtle disabled:cursor-default"
        >
          {installing ? (
            <Loader2 className="h-4 w-4 animate-spin" strokeWidth={2} />
          ) : installed ? (
            <Check className="h-4.5 w-4.5 text-emerald-500" strokeWidth={2.25} />
          ) : (
            <Plus className="h-4.5 w-4.5" strokeWidth={2} />
          )}
        </button>
      </div>
    </li>
  )
}

function MarketplaceCard({
  entry,
  installed,
  installing,
  onInstall,
  onOpenDetails
}: {
  entry: RegistryEntry
  installed: boolean
  installing: boolean
  onInstall: () => void
  onOpenDetails: () => void
}): ReactElement {
  const { t, i18n } = useTranslation('common')
  const title = pluginDisplayTitle(entry.name, i18n.language)
  const summary = pluginDisplaySummary(entry.name, i18n.language, entry.description)
  const actionLabel = installed ? t('pluginSysInstalled') : t('pluginSysInstall')
  const chips = [
    ...(entry.components ?? []).slice(0, 4),
    entry.permissions.length > 0
      ? t('pluginDetailPermCount', { count: entry.permissions.length })
      : null
  ].filter((v): v is string => Boolean(v))
  return (
    <li className={CARD_CLASS}>
      <div className="flex min-h-0 flex-1 items-start gap-3">
        <PluginIcon pluginId={entry.name} />
        <div className="min-w-0 flex-1">
          <button type="button" onClick={onOpenDetails} className="min-w-0 text-left">
            <h3 className="truncate text-[15px] font-semibold tracking-[-0.01em] text-ds-ink hover:text-accent">
              {title}
            </h3>
          </button>
          <div className="mt-0.5 truncate font-mono text-[12px] text-ds-faint">{entry.name}</div>
          <p
            className="mt-2 line-clamp-3 overflow-hidden text-[13px] leading-5 text-ds-muted"
            title={summary}
          >
            {summary || entry.source}
          </p>
          <MetaChips items={chips} />
        </div>
      </div>
      <div className="mt-auto flex items-center gap-2 border-t border-ds-border-muted pt-3.5">
        <span className="flex min-w-0 flex-1 items-center gap-1.5 text-[13px] text-ds-faint">
          <Download className="h-3.5 w-3.5 shrink-0" strokeWidth={1.75} />
          <span className="truncate font-mono">
            {entry.version ? `v${entry.version}` : entry.source}
          </span>
        </span>
        <button
          type="button"
          onClick={onOpenDetails}
          className="shrink-0 rounded-md border border-ds-border px-2 py-1 text-[12px] text-ds-muted hover:bg-ds-hover hover:text-ds-ink"
        >
          {t('pluginDetailsAction')}
        </button>
        <button
          type="button"
          onClick={onInstall}
          disabled={installed || installing}
          title={actionLabel}
          aria-label={actionLabel}
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-ds-muted transition hover:bg-ds-subtle disabled:cursor-default"
        >
          {installing ? (
            <Loader2 className="h-4 w-4 animate-spin" strokeWidth={2} />
          ) : installed ? (
            <Check className="h-4.5 w-4.5 text-emerald-500" strokeWidth={2.25} />
          ) : (
            <Plus className="h-4.5 w-4.5" strokeWidth={2} />
          )}
        </button>
      </div>
    </li>
  )
}

function PluginCard({ plugin, busy, onRemove, onOpenDetails }: {
  busy: boolean
  onRemove: () => void
  plugin: PluginRow
  onOpenDetails: () => void
}): ReactElement {
  const { i18n } = useTranslation('common')
  return <PluginListItem pluginId={plugin.name}
    title={pluginDisplayTitle(plugin.name, i18n.language)}
    summary={pluginDisplaySummary(plugin.name, i18n.language, plugin.description)}
    onOpen={onOpenDetails} busy={busy} onUse={() => void usePluginNow(plugin.name)}
    onRemove={plugin.scope === 'claude' || plugin.scope === 'override' ? undefined : onRemove} />
}
