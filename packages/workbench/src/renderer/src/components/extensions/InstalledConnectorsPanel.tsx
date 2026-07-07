import type { MouseEvent as ReactMouseEvent, ReactElement } from 'react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Cable, Loader2, Plus, Trash2 } from 'lucide-react'
import type { McpServerEntry } from '../../lib/mcp-json-merge'

export type ConnectorItem = {
  id: string
  name: string
  summary: string
  builtin: boolean
  enabled: boolean
  /** Entry to write into mcp.json when the user clicks 安装. Only built-in
   * presets carry this; once installed the preset migrates to the 已安装
   * tab as a normal user connector and this field is unset. */
  presetInstall?: McpServerEntry
}

type ConnectorTab = 'builtin' | 'installed' | 'marketplace'

type Props = {
  connectors: ConnectorItem[]
  loading: boolean
  busyId: string | null
  onToggle: (connector: ConnectorItem, enabled: boolean) => void
  onDelete: (connector: ConnectorItem) => void
  /** Install a built-in preset connector into mcp.json. */
  onInstallPreset?: (connector: ConnectorItem) => void
  /** Content rendered when the ModelScope 市场 tab is active. */
  marketplaceSlot?: ReactElement
}

/**
 * Installed-connectors list with 内置 / 已安装 / ModelScope 市场 segmented tabs,
 * mirroring the skills panel. Built-in presets show a one-click 安装 button;
 * user connectors (mcp.json servers) reveal a delete action on hover. The
 * marketplace tab renders `marketplaceSlot` (the ModelScope browser).
 */
export function InstalledConnectorsPanel({
  connectors,
  loading,
  busyId,
  onToggle,
  onDelete,
  onInstallPreset,
  marketplaceSlot
}: Props): ReactElement {
  const { t } = useTranslation('common')
  const [tab, setTab] = useState<ConnectorTab>('builtin')

  const builtinConnectors = connectors.filter((c) => c.builtin)
  const userConnectors = connectors.filter((c) => !c.builtin)
  const active = tab === 'builtin' ? builtinConnectors : userConnectors

  return (
    <div className="ds-content-card overflow-hidden rounded-2xl">
      <div className="flex items-center gap-5 border-b border-ds-border-muted px-5 pt-4">
        <TabButton active={tab === 'builtin'} count={builtinConnectors.length} onClick={() => setTab('builtin')}>
          {t('skillTabBuiltin')}
        </TabButton>
        <TabButton active={tab === 'installed'} count={userConnectors.length} onClick={() => setTab('installed')}>
          {t('skillTabInstalled')}
        </TabButton>
        <TabButton active={tab === 'marketplace'} onClick={() => setTab('marketplace')}>
          {t('marketplaceTitle')}
        </TabButton>
      </div>

      {tab === 'marketplace' ? null : loading ? (
        <div className="flex items-center gap-2 px-5 py-8 text-[13px] text-ds-muted">
          <Loader2 className="h-4 w-4 animate-spin" strokeWidth={2} />
          {t('skillsLoading')}
        </div>
      ) : active.length === 0 ? (
        <div className="px-5 py-10 text-center text-[13px] text-ds-faint">
          {tab === 'builtin' ? t('connectorsBuiltinEmpty') : t('connectorsInstalledEmpty')}
        </div>
      ) : (
        <ul className="divide-y divide-ds-border-muted/70">
          {active.map((connector) => (
            <ConnectorRow
              key={connector.id}
              connector={connector}
              busy={busyId === connector.id}
              onToggle={(enabled) => onToggle(connector, enabled)}
              onDelete={() => onDelete(connector)}
              onInstallPreset={onInstallPreset ? () => onInstallPreset(connector) : undefined}
            />
          ))}
        </ul>
      )}
      {/* MarketplaceBrowser stays mounted across tabs so the parent's top
          "重新加载" refresh signal reaches it even while the market tab is
          hidden — otherwise the signal would fire into an unmounted component
          and the catalog would never re-fetch. */}
      <div className={tab === 'marketplace' ? '' : 'hidden'}>
        {marketplaceSlot ?? null}
      </div>
    </div>
  )
}

function TabButton({
  active,
  count,
  onClick,
  children
}: {
  active: boolean
  count?: number
  onClick: () => void
  children: string
}): ReactElement {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`relative -mb-px flex items-center gap-1.5 border-b-2 pb-3 text-[15px] font-semibold transition ${
        active ? 'border-ds-ink text-ds-ink' : 'border-transparent text-ds-muted hover:text-ds-ink'
      }`}
    >
      {children}
      {count !== undefined ? (
        <span
          className={`inline-flex min-w-[18px] items-center justify-center rounded-full px-1.5 text-[11px] font-semibold ${
            active ? 'bg-ds-ink/10 text-ds-ink' : 'bg-ds-subtle text-ds-faint'
          }`}
        >
          {count}
        </span>
      ) : null}
    </button>
  )
}

function ConnectorRow({
  connector,
  busy,
  onToggle,
  onDelete,
  onInstallPreset
}: {
  connector: ConnectorItem
  busy: boolean
  onToggle: (enabled: boolean) => void
  onDelete: () => void
  onInstallPreset?: () => void
}): ReactElement {
  const { t } = useTranslation('common')
  const stopDelete = (event: ReactMouseEvent): void => {
    event.stopPropagation()
    onDelete()
  }
  const installable = connector.builtin && Boolean(connector.presetInstall) && onInstallPreset
  return (
    <li className="group flex items-center gap-4 px-5 py-4 transition hover:bg-ds-subtle/50">
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-ds-border bg-ds-card text-ds-muted">
        <Cable className="h-4.5 w-4.5" strokeWidth={1.6} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="truncate text-[15px] font-semibold text-ds-ink">{connector.name}</div>
        <p className="mt-0.5 line-clamp-1 font-mono text-[12px] leading-5 text-ds-muted" title={connector.summary}>
          {connector.summary}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {installable ? (
          <button
            type="button"
            onClick={() => onInstallPreset?.()}
            disabled={busy}
            className="inline-flex items-center gap-1.5 rounded-lg bg-ds-userbubble px-3 py-1.5 text-[12.5px] font-semibold text-ds-userbubbleFg shadow-sm transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-55"
          >
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={2} /> : <Plus className="h-3.5 w-3.5" strokeWidth={2} />}
            {t('pluginAdd')}
          </button>
        ) : null}
        {!connector.builtin ? (
          <button
            type="button"
            onClick={stopDelete}
            disabled={busy}
            title={t('connectorDelete')}
            aria-label={t('connectorDelete')}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-red-500 opacity-0 transition hover:bg-red-50 disabled:opacity-50 group-hover:opacity-100 focus-within:opacity-100 dark:hover:bg-red-950/30"
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" strokeWidth={2} /> : <Trash2 className="h-4 w-4" strokeWidth={1.75} />}
          </button>
        ) : null}
        {!installable ? (
          <ConnectorToggle
            checked={connector.enabled}
            disabled={connector.builtin || busy}
            onChange={onToggle}
          />
        ) : null}
      </div>
    </li>
  )
}

function ConnectorToggle({
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
