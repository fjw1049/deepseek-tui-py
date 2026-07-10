import type { MouseEvent as ReactMouseEvent, ReactElement } from 'react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Cable, Loader2, Trash2 } from 'lucide-react'
import { GlassSegmentedControl } from '../settings/GlassSegmentedControl'

export type ConnectorItem = {
  id: string
  name: string
  summary: string
  enabled: boolean
}

type ConnectorTab = 'installed' | 'marketplace'

type Props = {
  connectors: ConnectorItem[]
  loading: boolean
  busyId: string | null
  onToggle: (connector: ConnectorItem, enabled: boolean) => void
  onDelete: (connector: ConnectorItem) => void
  /** Content rendered when the ModelScope 市场 tab is active. */
  marketplaceSlot?: ReactElement
  /** Optional content pinned to the right of the tab row (e.g. a hint). */
  headerRight?: ReactElement
}

/**
 * Installed-connectors list with 已安装 / ModelScope 市场 segmented tabs, mirroring
 * the skills panel. The 已安装 tab shows the mcp.json servers with a delete
 * action on hover and an enable/disable toggle. The marketplace tab renders
 * `marketplaceSlot` (the ModelScope browser).
 */
export function InstalledConnectorsPanel({
  connectors,
  loading,
  busyId,
  onToggle,
  onDelete,
  marketplaceSlot,
  headerRight
}: Props): ReactElement {
  const { t } = useTranslation('common')
  const [tab, setTab] = useState<ConnectorTab>('installed')

  const tabItems = [
    { value: 'installed' as const, label: `${t('skillTabInstalled')} (${connectors.length})` },
    { value: 'marketplace' as const, label: t('marketplaceTitle') }
  ]

  return (
    <div className="ds-content-card overflow-hidden rounded-2xl">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-ds-border-muted px-5 py-3.5">
        <GlassSegmentedControl value={tab} onChange={setTab} items={tabItems} segmentClassName="px-3 py-1.5" />
        {headerRight ? <div className="min-w-0">{headerRight}</div> : null}
      </div>

      {tab === 'marketplace' ? null : loading ? (
        <div className="flex items-center gap-2 px-5 py-8 text-[13px] text-ds-muted">
          <Loader2 className="h-4 w-4 animate-spin" strokeWidth={2} />
          {t('skillsLoading')}
        </div>
      ) : connectors.length === 0 ? (
        <div className="px-5 py-10 text-center text-[13px] text-ds-faint">
          {t('connectorsInstalledEmpty')}
        </div>
      ) : (
        <ul className="divide-y divide-ds-border-muted/70">
          {connectors.map((connector) => (
            <ConnectorRow
              key={connector.id}
              connector={connector}
              busy={busyId === connector.id}
              onToggle={(enabled) => onToggle(connector, enabled)}
              onDelete={() => onDelete(connector)}
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

function ConnectorRow({
  connector,
  busy,
  onToggle,
  onDelete
}: {
  connector: ConnectorItem
  busy: boolean
  onToggle: (enabled: boolean) => void
  onDelete: () => void
}): ReactElement {
  const { t } = useTranslation('common')
  const stopDelete = (event: ReactMouseEvent): void => {
    event.stopPropagation()
    onDelete()
  }
  return (
    <li className="group flex items-center gap-4 px-5 py-4 transition hover:bg-ds-subtle/50 active:bg-ds-subtle/70">
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-ds-border bg-ds-card text-ds-muted">
        <Cable className="h-4.5 w-4.5" strokeWidth={1.6} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="truncate text-[15px] font-semibold text-ds-ink">{connector.name}</div>
        <p className="mt-0.5 line-clamp-1 font-mono text-[12px] leading-5 text-ds-muted" title={connector.summary}>
          {connector.summary}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-2 opacity-40 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
        <button
          type="button"
          onClick={stopDelete}
          disabled={busy}
          title={t('connectorDelete')}
          aria-label={t('connectorDelete')}
          className="ds-ext-row-action flex h-8 w-8 items-center justify-center rounded-lg text-red-500 transition hover:bg-red-50 disabled:opacity-50 dark:hover:bg-red-950/30"
        >
          {busy ? <Loader2 className="h-4 w-4 animate-spin" strokeWidth={2} /> : <Trash2 className="h-4 w-4" strokeWidth={1.75} />}
        </button>
        <ConnectorToggle checked={connector.enabled} disabled={busy} onChange={onToggle} />
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
      className={`ds-ext-toggle relative h-7 w-12 shrink-0 rounded-full transition disabled:cursor-not-allowed disabled:opacity-45 active:scale-[0.97] ${
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
