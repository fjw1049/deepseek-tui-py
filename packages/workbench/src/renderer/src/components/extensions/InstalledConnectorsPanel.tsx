import type { MouseEvent as ReactMouseEvent, ReactElement } from 'react'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Loader2, Trash2 } from 'lucide-react'
import { MarketplaceContentTabs } from './marketplace-ui'
import { partitionConnectorsByGroup } from '../../lib/connector-groups'
import {
  composerConnectorDotClass,
  composerConnectorDotTone,
  type ConnectorRuntimeStatus
} from '../../lib/composer-connectors'
import type { McpLoadPolicy } from '../../lib/mcp-json-merge'

export type ConnectorItem = {
  id: string
  name: string
  summary: string
  enabled: boolean
  loadPolicy?: McpLoadPolicy
  catalog?: string
  status?: ConnectorRuntimeStatus
  error?: string | null
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
 * Connector list with 已安装 / 市场 tabs. 已安装 groups 默认 (progressive)
 * and 激活 (@ / on_focus).
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

  const { default: defaultConnectors, activated } = useMemo(
    () => partitionConnectorsByGroup(connectors),
    [connectors]
  )

  const tabItems = [
    { value: 'installed' as const, label: t('skillTabInstalled') },
    { value: 'marketplace' as const, label: t('marketplaceTitle') }
  ]

  return (
    <div className="ds-content-card overflow-hidden rounded-2xl">
      <MarketplaceContentTabs value={tab} onChange={setTab} items={tabItems} trailing={headerRight} />

      {tab === 'marketplace' ? null : loading ? (
        <div className="flex items-center gap-2 px-5 py-8 text-[13px] text-ds-muted">
          <Loader2 className="h-4 w-4 animate-spin" strokeWidth={2} />
          {t('skillsLoading')}
        </div>
      ) : (
        <div>
          <ConnectorGroup
            title={t('connectorTabDefault')}
            empty={t('connectorSectionDefaultEmpty')}
          >
            {defaultConnectors.map((connector) => (
              <ConnectorRow
                key={connector.id}
                connector={connector}
                busy={busyId === connector.id}
                onToggle={(enabled) => onToggle(connector, enabled)}
                onDelete={() => onDelete(connector)}
              />
            ))}
          </ConnectorGroup>
          <ConnectorGroup
            title={t('connectorTabActivated')}
            empty={t('connectorSectionActivatedEmpty')}
          >
            {activated.map((connector) => (
              <ConnectorRow
                key={connector.id}
                connector={connector}
                busy={busyId === connector.id}
                onToggle={(enabled) => onToggle(connector, enabled)}
                onDelete={() => onDelete(connector)}
              />
            ))}
          </ConnectorGroup>
        </div>
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

function ConnectorGroup({
  title,
  empty,
  children
}: {
  title: string
  empty: string
  children: ReactElement[]
}): ReactElement {
  return (
    <section className="border-t border-ds-border-muted/70 first:border-t-0">
      <h3 className="px-5 pt-4 pb-1 text-[11px] font-semibold tracking-[0.08em] text-ds-faint">
        {title}
      </h3>
      {children.length === 0 ? (
        <div className="px-5 pb-4 text-[13px] text-ds-faint">{empty}</div>
      ) : (
        <ul className="divide-y divide-ds-border-muted/70">{children}</ul>
      )}
    </section>
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
  const status = connector.status
  const tone =
    status && status !== 'disabled' ? composerConnectorDotTone({ status }) : null
  const errorSuffix = connector.error ? `：${connector.error}` : ''
  const statusLabel =
    status === 'connected'
      ? t('connectorStatusConnected')
      : status === 'connecting'
        ? t('composerConnectorConnectingHint')
        : status === 'failed'
          ? t('connectorStatusFailed', { error: errorSuffix })
          : status === 'disabled'
            ? t('connectorStatusDisabled')
            : null
  return (
    <li className="group flex items-center gap-4 px-5 py-4 transition hover:bg-ds-subtle/50 active:bg-ds-subtle/70">
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-2">
          {tone ? (
            <span
              className={`h-2 w-2 shrink-0 rounded-full ${composerConnectorDotClass(tone)}`}
              title={statusLabel ?? undefined}
              aria-hidden
            />
          ) : null}
          <div className="truncate text-[15px] font-semibold text-ds-ink">{connector.name}</div>
        </div>
        <p className="mt-0.5 line-clamp-1 font-mono text-[12px] leading-5 text-ds-muted" title={connector.summary}>
          {connector.summary}
        </p>
        {statusLabel ? (
          <p
            className={`mt-0.5 line-clamp-1 text-[12px] leading-5 ${
              status === 'failed'
                ? 'text-red-500/80'
                : status === 'connecting'
                  ? 'text-amber-600 dark:text-amber-400'
                  : status === 'connected'
                    ? 'text-emerald-600 dark:text-emerald-400'
                    : 'text-ds-faint'
            }`}
            title={statusLabel}
          >
            {statusLabel}
          </p>
        ) : null}
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
