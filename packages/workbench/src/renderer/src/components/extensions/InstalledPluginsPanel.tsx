import type { ReactElement } from 'react'
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import {
  Check,
  Download,
  Loader2,
  Plus,
  Puzzle,
  RefreshCw,
  Shield,
  ShieldCheck,
  Store,
  Trash2,
  X
} from 'lucide-react'
import { GlassSegmentedControl } from '../settings/GlassSegmentedControl'
import {
  pluginDisplayDetail,
  pluginDisplaySummary,
  pluginDisplayTitle,
  pluginVisual
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
  onTrust: (plugin: PluginRow) => void
  onUpdate: (plugin: PluginRow) => void
  onRemove: (plugin: PluginRow) => void
  onMarketplaceInstall: (entry: RegistryEntry) => void
  onMarketplaceAdd: (spec: string) => Promise<boolean>
  onMarketplaceUpdate: (name: string) => void
  onMarketplaceRemove: (name: string) => void
  onMarketplacePluginInstall: (spec: string) => void
  headerRight?: ReactElement
}

const CARD_CLASS =
  'group relative flex min-h-[200px] flex-col rounded-2xl border border-black/[0.04] bg-white p-4 shadow-[0_1px_2px_rgba(15,23,42,0.04)] transition hover:-translate-y-0.5 hover:shadow-[0_8px_24px_rgba(15,23,42,0.08)] dark:border-white/10 dark:bg-ds-card'

function pluginKey(plugin: PluginRow): string {
  return `${plugin.scope}:${plugin.name}`
}

function scopeLabel(scope: string, t: (key: string) => string): string {
  switch (scope) {
    case 'user':
      return t('pluginSysScopeUser')
    case 'project':
      return t('pluginSysScopeProject')
    case 'claude':
      return t('pluginSysScopeClaude')
    case 'override':
      return t('pluginSysScopeOverride')
    default:
      return scope
  }
}

function componentKeys(components: PluginRow['components']): string[] {
  return (
    [
      components.skills ? 'skills' : null,
      components.rules ? 'rules' : null,
      components.agents ? 'agents' : null,
      components.commands ? 'commands' : null,
      components.hooks ? 'hooks' : null,
      components.mcp_servers ? 'mcp' : null
    ] as const
  ).filter((v): v is string => v != null)
}

function componentLabel(key: string, t: (key: string) => string): string {
  switch (key) {
    case 'skills':
      return t('pluginComponentSkills')
    case 'rules':
      return t('pluginComponentRules')
    case 'agents':
      return t('pluginComponentAgents')
    case 'commands':
      return t('pluginComponentCommands')
    case 'hooks':
      return t('pluginComponentHooks')
    case 'mcp':
      return t('pluginComponentMcp')
    default:
      return key
  }
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

function TrustSwitch({
  checked,
  disabled,
  onChange
}: {
  checked: boolean
  disabled?: boolean
  onChange: () => void
}): ReactElement {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={(event) => {
        event.stopPropagation()
        onChange()
      }}
      className={`relative h-6 w-11 shrink-0 rounded-full transition-colors ${
        checked
          ? 'bg-emerald-500 shadow-sm'
          : 'border border-ds-border bg-neutral-300 shadow-inner dark:border-neutral-500 dark:bg-neutral-600'
      } ${disabled ? 'opacity-40' : 'cursor-pointer'}`}
    >
      <span
        className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${
          checked ? 'left-[22px]' : 'left-0.5'
        } ${checked ? '' : 'ring-1 ring-black/10 dark:ring-white/20'}`}
      />
    </button>
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
  onTrust,
  onUpdate,
  onRemove,
  onMarketplaceInstall,
  onMarketplaceAdd,
  onMarketplaceUpdate,
  onMarketplaceRemove,
  onMarketplacePluginInstall,
  headerRight
}: Props): ReactElement {
  const { t } = useTranslation('common')
  const [tab, setTab] = useState<PluginTab>('installed')
  const [detail, setDetail] = useState<DetailTarget | null>(null)

  const tabItems: Array<{ value: PluginTab; label: string }> = [
    { value: 'installed', label: t('skillTabInstalled') },
    ...(marketplaceEnabled
      ? [{ value: 'marketplace' as const, label: t('pluginSysMarketplace') }]
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
    <div className="ds-content-card overflow-hidden rounded-2xl">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-ds-border-muted px-5 py-3.5">
        {tabItems.length > 1 ? (
          <GlassSegmentedControl
            value={tab}
            onChange={setTab}
            items={tabItems}
            segmentClassName="px-3 py-1.5"
          />
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
          <div className="bg-[color-mix(in_srgb,var(--ds-main)_88%,#f4f1ea)] px-4 py-4 dark:bg-ds-subtle/30 sm:px-5 sm:py-5">
            <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {plugins.map((plugin) => (
                <PluginCard
                  key={pluginKey(plugin)}
                  plugin={plugin}
                  busy={busyName === plugin.name}
                  onOpenDetails={() => openInstalled(plugin)}
                  onTrust={() => onTrust(plugin)}
                  onRemove={() => onRemove(plugin)}
                />
              ))}
            </ul>
          </div>
        )
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
            <div className="bg-[color-mix(in_srgb,var(--ds-main)_88%,#f4f1ea)] px-4 py-4 dark:bg-ds-subtle/30 sm:px-5 sm:py-5">
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
              onTrust={
                detail.kind === 'installed' ? () => onTrust(detail.plugin) : undefined
              }
              onUpdate={
                detail.kind === 'installed' ? () => onUpdate(detail.plugin) : undefined
              }
              onRemove={
                detail.kind === 'installed'
                  ? () => {
                      onRemove(detail.plugin)
                      setDetail(null)
                    }
                  : undefined
              }
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

function PluginDetailDrawer({
  detail,
  busy,
  installed,
  onClose,
  onTrust,
  onUpdate,
  onRemove,
  onInstall
}: {
  detail: DetailTarget
  busy: boolean
  installed: boolean
  onClose: () => void
  onTrust?: () => void
  onUpdate?: () => void
  onRemove?: () => void
  onInstall?: () => void
}): ReactElement {
  const { t, i18n } = useTranslation('common')
  const name =
    detail.kind === 'installed'
      ? detail.plugin.name
      : detail.kind === 'registry'
        ? detail.entry.name
        : detail.entry.name
  const title = pluginDisplayTitle(name, i18n.language)
  const visual = pluginVisual(name)
  const Icon = visual.icon
  const description =
    detail.kind === 'installed'
      ? detail.plugin.description
      : detail.kind === 'registry'
        ? detail.entry.description
        : detail.entry.description
  const version =
    detail.kind === 'installed'
      ? detail.plugin.version
      : detail.kind === 'registry'
        ? detail.entry.version
        : detail.entry.version
  const permissions =
    detail.kind === 'installed'
      ? detail.plugin.permissions
      : detail.kind === 'registry'
        ? detail.entry.permissions
        : []
  const summary = pluginDisplaySummary(name, i18n.language, description)
  const packageDetail = pluginDisplayDetail(name, i18n.language, description)
  const showPackageDesc = packageDetail.length > 0 && packageDetail !== summary
  const componentsList =
    detail.kind === 'installed'
      ? componentKeys(detail.plugin.components).map((key) => componentLabel(key, t))
      : detail.kind === 'registry'
        ? detail.entry.components
        : detail.entry.category
          ? [detail.entry.category]
          : []
  const hasExecutable =
    detail.kind === 'installed' &&
    (detail.plugin.components.hooks || detail.plugin.components.mcp_servers)
  const managedElsewhere =
    detail.kind === 'installed' &&
    (detail.plugin.scope === 'claude' || detail.plugin.scope === 'override')

  return (
    <>
      <button
        type="button"
        aria-label={t('pluginCloseDetail')}
        className="fixed inset-0 z-[80] bg-black/20 dark:bg-black/40"
        onClick={onClose}
      />
      <div className="ds-automation-drawer fixed inset-y-0 right-0 z-[90] flex w-full max-w-[440px] flex-col">
        <div className="flex items-start justify-between gap-3 border-b border-ds-border-muted px-5 py-4">
          <div className="flex min-w-0 items-start gap-3">
            <div
              className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-[12px] shadow-sm ${visual.tile}`}
            >
              <Icon className="h-5 w-5" strokeWidth={1.9} />
            </div>
            <div className="min-w-0">
              <h2 className="truncate text-[16px] font-semibold text-ds-ink">{title}</h2>
              <p className="mt-1 truncate font-mono text-[12px] text-ds-muted">
                {name}
                {version ? ` · v${version}` : ''}
              </p>
              {detail.kind === 'installed' ? (
                <p className="mt-1 text-[12px] text-ds-faint">
                  {scopeLabel(detail.plugin.scope, t)}
                  {' · '}
                  {detail.plugin.enabled
                    ? t('pluginDetailEnabledOn')
                    : t('pluginDetailEnabledOff')}
                  {' · '}
                  {hasExecutable
                    ? detail.plugin.trusted
                      ? t('pluginSysTrusted')
                      : t('pluginSysUntrusted')
                    : t('pluginDetailContentOnly')}
                </p>
              ) : null}
            </div>
          </div>
          <button
            type="button"
            title={t('pluginCloseDetail')}
            onClick={onClose}
            className="inline-flex shrink-0 items-center gap-1 rounded-md border border-ds-border px-2.5 py-1.5 text-[12px] text-ds-muted hover:bg-ds-hover"
          >
            <X className="h-3.5 w-3.5" />
            {t('pluginCloseDetail')}
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-auto p-5">
          {detail.kind === 'installed' ? (
            <div className="mb-5 flex flex-wrap items-center gap-2">
              {hasExecutable ? (
                <button
                  type="button"
                  disabled={busy}
                  onClick={onTrust}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-ds-border bg-ds-card px-3 py-2 text-[12px] font-medium text-ds-ink hover:bg-ds-hover disabled:opacity-50"
                >
                  {detail.plugin.trusted ? (
                    <Shield className="h-3.5 w-3.5" strokeWidth={1.75} />
                  ) : (
                    <ShieldCheck className="h-3.5 w-3.5" strokeWidth={1.75} />
                  )}
                  {detail.plugin.trusted
                    ? t('pluginSysUntrustAction')
                    : t('pluginSysTrustAction')}
                </button>
              ) : null}
              {managedElsewhere ? null : (
                <>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={onUpdate}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-ds-border bg-ds-card px-3 py-2 text-[12px] font-medium text-ds-ink hover:bg-ds-hover disabled:opacity-50"
                  >
                    {busy ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={2} />
                    ) : (
                      <RefreshCw className="h-3.5 w-3.5" strokeWidth={1.75} />
                    )}
                    {t('pluginSysUpdateAction')}
                  </button>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={onRemove}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-red-200 bg-ds-card px-3 py-2 text-[12px] font-medium text-red-600 hover:bg-red-50 disabled:opacity-50 dark:border-red-900/50 dark:text-red-400 dark:hover:bg-red-950/30"
                  >
                    <Trash2 className="h-3.5 w-3.5" strokeWidth={1.75} />
                    {t('pluginSysRemoveAction')}
                  </button>
                </>
              )}
            </div>
          ) : (
            <div className="mb-5">
              <button
                type="button"
                disabled={busy || installed}
                onClick={onInstall}
                className="inline-flex items-center gap-1.5 rounded-lg bg-accent/10 px-3 py-2 text-[12px] font-medium text-accent transition hover:bg-accent/20 disabled:opacity-50"
              >
                {busy ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={2} />
                ) : installed ? (
                  <Check className="h-3.5 w-3.5" strokeWidth={2.25} />
                ) : (
                  <Download className="h-3.5 w-3.5" strokeWidth={1.75} />
                )}
                {installed ? t('pluginSysInstalled') : t('pluginSysInstall')}
              </button>
            </div>
          )}

          <h3 className="text-[12px] font-semibold text-ds-faint">{t('pluginDetailAbout')}</h3>
          <p className="mt-2 whitespace-pre-wrap text-[13px] leading-6 text-ds-ink">
            {summary || '—'}
          </p>
          {showPackageDesc ? (
            <>
              <h3 className="mt-4 text-[12px] font-semibold text-ds-faint">
                {t('pluginDetailPackageDesc')}
              </h3>
              <p className="mt-2 whitespace-pre-wrap text-[13px] leading-6 text-ds-muted">
                {packageDetail}
              </p>
            </>
          ) : null}

          <h3 className="mt-5 text-[12px] font-semibold text-ds-faint">{t('pluginDetailHowToUse')}</h3>
          <p className="mt-2 text-[13px] leading-6 text-ds-muted">{t('pluginSysScenarioHint')}</p>
          {hasExecutable && detail.kind === 'installed' && !detail.plugin.trusted ? (
            <p className="mt-2 rounded-lg bg-amber-500/10 px-3 py-2 text-[12px] leading-5 text-amber-800 dark:text-amber-200">
              {t('pluginSysUntrustedHint')}
            </p>
          ) : null}

          <dl className="mt-5 grid grid-cols-2 gap-3 border-y border-ds-border-muted py-4 text-[12px]">
            {detail.kind === 'installed' ? (
              <>
                <div>
                  <dt className="text-ds-faint">{t('pluginDetailScope')}</dt>
                  <dd className="mt-1 text-ds-ink">{scopeLabel(detail.plugin.scope, t)}</dd>
                </div>
                <div>
                  <dt className="text-ds-faint">{t('pluginDetailVersion')}</dt>
                  <dd className="mt-1 text-ds-ink">{version ? `v${version}` : '—'}</dd>
                </div>
                <div>
                  <dt className="text-ds-faint">{t('pluginDetailEnabled')}</dt>
                  <dd className="mt-1 text-ds-ink">
                    {detail.plugin.enabled
                      ? t('pluginDetailEnabledOn')
                      : t('pluginDetailEnabledOff')}
                  </dd>
                </div>
                <div>
                  <dt className="text-ds-faint">{t('pluginDetailTrust')}</dt>
                  <dd className="mt-1 text-ds-ink">
                    {hasExecutable
                      ? detail.plugin.trusted
                        ? t('pluginSysTrusted')
                        : t('pluginSysUntrusted')
                      : t('pluginDetailContentOnly')}
                  </dd>
                </div>
                <div className="col-span-2">
                  <dt className="text-ds-faint">{t('pluginDetailPath')}</dt>
                  <dd className="mt-1 break-all font-mono text-[11px] text-ds-ink">
                    {detail.plugin.path || '—'}
                  </dd>
                </div>
              </>
            ) : detail.kind === 'registry' ? (
              <>
                <div>
                  <dt className="text-ds-faint">{t('pluginDetailVersion')}</dt>
                  <dd className="mt-1 text-ds-ink">{version ? `v${version}` : '—'}</dd>
                </div>
                <div>
                  <dt className="text-ds-faint">{t('pluginSysPermissions')}</dt>
                  <dd className="mt-1 text-ds-ink">
                    {t('pluginDetailPermCount', { count: permissions.length })}
                  </dd>
                </div>
                <div className="col-span-2">
                  <dt className="text-ds-faint">{t('pluginDetailSource')}</dt>
                  <dd className="mt-1 break-all font-mono text-[11px] text-ds-ink">
                    {detail.entry.source}
                  </dd>
                </div>
              </>
            ) : (
              <>
                <div>
                  <dt className="text-ds-faint">{t('pluginDetailVersion')}</dt>
                  <dd className="mt-1 text-ds-ink">{version ? `v${version}` : '—'}</dd>
                </div>
                <div>
                  <dt className="text-ds-faint">{t('pluginDetailSource')}</dt>
                  <dd className="mt-1 break-all font-mono text-[11px] text-ds-ink">
                    {detail.entry.spec}
                  </dd>
                </div>
              </>
            )}
          </dl>

          <h3 className="mt-5 text-[13px] font-semibold text-ds-ink">
            {t('pluginDetailComponents')}
            {componentsList.length > 0 ? (
              <span className="ml-1.5 font-normal text-ds-faint">({componentsList.length})</span>
            ) : null}
          </h3>
          {componentsList.length === 0 ? (
            <p className="mt-2 text-[12px] text-ds-muted">—</p>
          ) : (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {componentsList.map((label) => (
                <span
                  key={label}
                  className="inline-flex items-center rounded-full border border-ds-border-muted px-2.5 py-1 text-[12px] text-ds-ink"
                >
                  {label}
                </span>
              ))}
            </div>
          )}

          <h3 className="mt-5 text-[13px] font-semibold text-ds-ink">
            {t('pluginSysPermissions')}
            {permissions.length > 0 ? (
              <span className="ml-1.5 font-normal text-ds-faint">
                ({t('pluginDetailPermCount', { count: permissions.length })})
              </span>
            ) : null}
          </h3>
          {permissions.length === 0 ? (
            <p className="mt-2 text-[12px] text-ds-muted">{t('pluginDetailNoPermissions')}</p>
          ) : (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {permissions.map((perm) => (
                <span
                  key={perm}
                  className="inline-flex items-center rounded-full border border-ds-border-muted px-2.5 py-1 font-mono text-[11px] text-ds-ink"
                >
                  {perm}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>
    </>
  )
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
                <div className="bg-[color-mix(in_srgb,var(--ds-main)_88%,#f4f1ea)] px-4 py-4 dark:bg-ds-subtle/30 sm:px-5">
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
  const visual = pluginVisual(entry.name)
  const Icon = visual.icon
  const title = pluginDisplayTitle(entry.name, i18n.language)
  const summary = pluginDisplaySummary(entry.name, i18n.language, entry.description)
  const actionLabel = installed ? t('pluginSysInstalled') : t('pluginSysInstall')
  const chips = [entry.category, entry.version ? `v${entry.version}` : null].filter(
    (v): v is string => Boolean(v)
  )
  return (
    <li className={CARD_CLASS}>
      <div className="flex min-h-0 flex-1 items-start gap-3">
        <div
          className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-[12px] shadow-sm ${visual.tile}`}
        >
          <Icon className="h-5 w-5" strokeWidth={1.9} />
        </div>
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
  const visual = pluginVisual(entry.name)
  const Icon = visual.icon
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
        <div
          className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-[12px] shadow-sm ${visual.tile}`}
        >
          <Icon className="h-5 w-5" strokeWidth={1.9} />
        </div>
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

function PluginCard({
  plugin,
  busy,
  onOpenDetails,
  onTrust,
  onRemove
}: {
  plugin: PluginRow
  busy: boolean
  onOpenDetails: () => void
  onTrust: () => void
  onRemove: () => void
}): ReactElement {
  const { t, i18n } = useTranslation('common')
  const visual = pluginVisual(plugin.name)
  const Icon = visual.icon
  const title = pluginDisplayTitle(plugin.name, i18n.language)
  const summary = pluginDisplaySummary(plugin.name, i18n.language, plugin.description)
  const hasExecutable = plugin.components.hooks || plugin.components.mcp_servers
  const managedElsewhere = plugin.scope === 'claude' || plugin.scope === 'override'
  const chips = [
    ...componentKeys(plugin.components).map((key) => componentLabel(key, t)),
    plugin.permissions.length > 0
      ? t('pluginDetailPermCount', { count: plugin.permissions.length })
      : null
  ].filter((v): v is string => Boolean(v))
  const metaLeft = [
    plugin.version ? `v${plugin.version}` : null,
    scopeLabel(plugin.scope, t),
    hasExecutable
      ? plugin.trusted
        ? t('pluginSysTrusted')
        : t('pluginSysUntrusted')
      : t('pluginDetailContentOnly')
  ]
    .filter(Boolean)
    .join(' · ')
  const removeLabel = t('pluginSysRemoveAction')

  return (
    <li className={CARD_CLASS}>
      <div className="flex min-h-0 flex-1 items-start gap-3">
        <div
          className={`flex h-11 w-11 shrink-0 items-center justify-center rounded-[12px] shadow-sm ${visual.tile}`}
        >
          <Icon className="h-5 w-5" strokeWidth={1.9} />
        </div>
        <div className="min-w-0 flex-1">
          <button type="button" onClick={onOpenDetails} className="min-w-0 text-left">
            <h3 className="truncate text-[15px] font-semibold tracking-[-0.01em] text-ds-ink hover:text-accent">
              {title}
            </h3>
          </button>
          <div className="mt-0.5 truncate font-mono text-[12px] text-ds-faint">{plugin.name}</div>
          <p
            className="mt-2 line-clamp-3 overflow-hidden text-[13px] leading-5 text-ds-muted"
            title={summary}
          >
            {summary || '—'}
          </p>
          <MetaChips items={chips} />
        </div>
      </div>

      <div className="mt-auto flex items-center gap-2 border-t border-ds-border-muted pt-3.5">
        <span
          className="flex min-w-0 flex-1 items-center gap-1.5 text-[13px] text-ds-faint"
          title={hasExecutable && !plugin.trusted ? t('pluginSysUntrustedHint') : undefined}
        >
          {hasExecutable ? (
            plugin.trusted ? (
              <ShieldCheck
                className="h-3.5 w-3.5 shrink-0 text-emerald-600 dark:text-emerald-400"
                strokeWidth={2}
              />
            ) : (
              <Shield
                className="h-3.5 w-3.5 shrink-0 text-amber-600 dark:text-amber-400"
                strokeWidth={2}
              />
            )
          ) : (
            <Puzzle className="h-3.5 w-3.5 shrink-0" strokeWidth={1.75} />
          )}
          <span className="truncate">{metaLeft}</span>
          {busy ? <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" strokeWidth={2} /> : null}
        </span>
        <button
          type="button"
          onClick={onOpenDetails}
          className="shrink-0 rounded-md border border-ds-border px-2 py-1 text-[12px] text-ds-muted hover:bg-ds-hover hover:text-ds-ink"
        >
          {t('pluginDetailsAction')}
        </button>
        {managedElsewhere ? null : (
          <button
            type="button"
            disabled={busy}
            onClick={(event) => {
              event.stopPropagation()
              onRemove()
            }}
            title={removeLabel}
            aria-label={removeLabel}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-red-500 transition hover:bg-red-50 disabled:opacity-50 dark:hover:bg-red-950/30"
          >
            <Trash2 className="h-3.5 w-3.5" strokeWidth={1.75} />
          </button>
        )}
        {hasExecutable ? (
          <TrustSwitch checked={plugin.trusted} disabled={busy} onChange={onTrust} />
        ) : null}
      </div>
    </li>
  )
}
