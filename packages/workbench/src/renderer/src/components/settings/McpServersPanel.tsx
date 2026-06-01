import type { ReactElement } from 'react'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronDown, ExternalLink, FolderOpen, Loader2, RefreshCw } from 'lucide-react'
import { MCP_MARKETPLACE_URL } from '@shared/marketplace-links'
import { openExternalUrl } from '../../lib/open-marketplace'
import { listMcpServers, setMcpServerEnabled } from '../../lib/mcp-json-merge'
import { SettingsActionToolbar, settingsToolbarButtonClass } from './SettingsActionToolbar'

type InlineNotice = {
  tone: 'success' | 'error' | 'info'
  message: string
}

type Props = {
  configPath: string
  configText: string
  configExists: boolean
  loading: boolean
  busy: boolean
  notice: InlineNotice | null
  onConfigTextChange: (value: string) => void
  onReload: () => void | Promise<void>
  onSave: (content?: string, quiet?: boolean) => void | Promise<void>
  onOpenConfigFolder: () => void | Promise<void>
}

export function McpServersPanel({
  configPath,
  configText,
  configExists,
  loading,
  busy,
  notice,
  onConfigTextChange,
  onReload,
  onSave,
  onOpenConfigFolder
}: Props): ReactElement {
  const { t } = useTranslation('settings')
  const [advancedOpen, setAdvancedOpen] = useState(false)

  const servers = useMemo(() => {
    try {
      return listMcpServers(configText)
    } catch {
      return []
    }
  }, [configText])

  const toggleServer = (serverId: string, enabled: boolean): void => {
    try {
      const next = setMcpServerEnabled(configText, serverId, enabled)
      onConfigTextChange(next)
      void onSave(next, true)
    } catch {
      /* invalid JSON — user can fix in advanced editor */
    }
  }

  return (
    <div className="flex w-full flex-col gap-4">
      <p className="max-w-3xl text-[13px] leading-6 text-ds-muted">{t('mcpListDesc')}</p>
      <code className="block w-full break-all rounded-lg bg-ds-main/70 px-3 py-2 font-mono text-[12px] text-ds-faint">
        {configPath}
      </code>

      {loading ? (
        <div className="flex w-full items-center gap-2 py-6 text-[13px] text-ds-muted">
          <Loader2 className="h-4 w-4 animate-spin" />
          {t('loading')}
        </div>
      ) : servers.length === 0 ? (
        <div className="w-full rounded-lg border border-dashed border-ds-border bg-ds-main/40 px-4 py-6 text-center text-[13px] leading-6 text-ds-muted">
          {configExists ? t('mcpListEmpty') : t('mcpFileStatusMissing')}
        </div>
      ) : (
        <ul className="w-full max-h-[520px] divide-y divide-ds-border-muted overflow-y-auto rounded-lg border border-ds-border bg-ds-card">
          {servers.map((server) => (
            <li
              key={server.id}
              className="grid grid-cols-[minmax(0,1fr)_auto] gap-4 px-4 py-3"
            >
              <div className="min-w-0 flex-1">
                <div className="text-[14px] font-semibold text-ds-ink">{server.id}</div>
                <div className="mt-0.5 truncate font-mono text-[11px] text-ds-faint">{server.summary}</div>
                <div className="mt-1 text-[11px] text-ds-muted">
                  {server.enabled ? t('mcpServerEnabled') : t('mcpServerDisabled')}
                </div>
              </div>
              <div className="flex min-w-12 justify-end self-center">
                <McpToggle
                  checked={server.enabled}
                  disabled={busy || loading}
                  onChange={(enabled) => toggleServer(server.id, enabled)}
                />
              </div>
            </li>
          ))}
        </ul>
      )}

      <p className="w-full text-[12px] leading-5 text-ds-faint">{t('mcpRuntimeHint')}</p>

      <SettingsActionToolbar className="w-full">
        <button
          type="button"
          onClick={() => void onReload()}
          disabled={busy || loading}
          className={settingsToolbarButtonClass(busy || loading)}
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} strokeWidth={1.75} />
          {t('mcpReload')}
        </button>
        <button
          type="button"
          onClick={() => void onOpenConfigFolder()}
          className={settingsToolbarButtonClass()}
        >
          <FolderOpen className="h-4 w-4" />
          {t('mcpOpenConfigFile')}
        </button>
        <button
          type="button"
          onClick={() => openExternalUrl(MCP_MARKETPLACE_URL)}
          className={settingsToolbarButtonClass()}
        >
          <ExternalLink className="h-4 w-4" strokeWidth={1.75} />
          {t('mcpOpenMarketplace')}
        </button>
      </SettingsActionToolbar>

      <details
        open={advancedOpen}
        onToggle={(e) => setAdvancedOpen(e.currentTarget.open)}
        className="w-full rounded-lg border border-ds-border bg-ds-main/40"
      >
        <summary className="flex cursor-pointer list-none items-center justify-between gap-2 px-4 py-3 text-[13px] font-medium text-ds-ink [&::-webkit-details-marker]:hidden">
          {t('mcpAdvancedJson')}
          <ChevronDown
            className={`h-4 w-4 shrink-0 text-ds-faint transition ${advancedOpen ? 'rotate-180' : ''}`}
            strokeWidth={1.75}
          />
        </summary>
        <div className="border-t border-ds-border-muted px-3 pb-3 pt-2">
          <p className="mb-2 text-[12px] leading-5 text-ds-muted">{t('mcpMarketplaceJsonHint')}</p>
          <textarea
            value={configText}
            onChange={(e) => onConfigTextChange(e.target.value)}
            spellCheck={false}
            className="min-h-[200px] w-full rounded-xl border border-ds-border bg-ds-card px-3 py-2 font-mono text-[12px] leading-5 text-ds-ink shadow-sm focus:border-accent/40 focus:outline-none focus:ring-1 focus:ring-accent/30"
          />
          <button
            type="button"
            onClick={() => void onSave()}
            disabled={busy || loading}
            className="mt-2 inline-flex items-center gap-1.5 rounded-xl bg-ds-userbubble px-3 py-1.5 text-[12px] font-medium text-ds-userbubbleFg shadow-sm transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-55"
          >
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={2} /> : null}
            {t('mcpSave')}
          </button>
        </div>
      </details>

      {notice ? (
        <div
          className={`w-full rounded-lg border px-3 py-2 text-[12px] ${
            notice.tone === 'error'
              ? 'border-red-300/80 bg-red-50 text-red-800 dark:border-red-800/70 dark:bg-red-950/25 dark:text-red-200'
              : notice.tone === 'success'
                ? 'border-emerald-300/80 bg-emerald-50 text-emerald-900 dark:border-emerald-800/70 dark:bg-emerald-950/25 dark:text-emerald-100'
                : 'border-ds-border bg-ds-main/50 text-ds-muted'
          }`}
        >
          {notice.message}
        </div>
      ) : null}
    </div>
  )
}

export function McpToggle({
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
