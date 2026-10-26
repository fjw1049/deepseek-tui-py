import { CuaApprovedApps } from '../cua-preview/CuaApprovedApps'
import { CuaPermissionsDialog } from '../cua-preview/CuaPermissionsDialog'
import { usePluginNow } from './start-chat-with-plugin'
import { PluginDescription } from './PluginDescription'
import { createPortal } from 'react-dom'
import { PluginListItem } from './PluginListItem'
import { PluginDialog } from './PluginDialog'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { cacheSettingsSnapshot } from '../../lib/settings-snapshot'

type Status = { supported: boolean; installed: boolean; enabled: boolean; readiness?: string; reason?: string | null }

async function readCuaStatus(): Promise<Status> {
  const response = await window.dsGui.runtimeRequest('/v1/cua/status', 'GET')
  if (!response.ok) throw new Error('Status unavailable')
  const value = JSON.parse(response.body) as Status
  if (!value || ['supported', 'installed', 'enabled'].some(key => typeof value[key as keyof Status] !== 'boolean')) {
    throw new Error('Invalid status')
  }
  return value
}

export function ComputerUsePluginCard(): React.JSX.Element {
  const { t } = useTranslation('common')
  const operationInFlight = useRef(false)
  const [permissionsOpen, setPermissionsOpen] = useState(false)
  const [open, setOpen] = useState(false)
  const [status, setStatus] = useState<Status | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(false)
  const [applied, setApplied] = useState(false)
  const refresh = useCallback(async () => {
    if (operationInFlight.current) return
    operationInFlight.current = true
    setBusy(true)
    setError(false)
    try {
      setStatus(await readCuaStatus())
      setApplied(false)
    } catch { setError(true) }
    finally { operationInFlight.current = false; setBusy(false) }
  }, [])
  useEffect(() => { void refresh() }, [refresh])

  const toggle = async (): Promise<boolean> => {
    if (!status || operationInFlight.current) return false
    operationInFlight.current = true
    setApplied(false)
    setBusy(true)
    setError(false)
    try {
      const settings = await window.dsGui.setSettings({ cuaEnabled: !status.enabled })
      cacheSettingsSnapshot(settings)
      const actual = await readCuaStatus()
      setStatus(actual)
      if (actual.enabled !== settings.cuaEnabled) throw new Error('Runtime settings not applied')
      setApplied(true)
      return true
    } catch { setError(true); return false }
    finally { operationInFlight.current = false; setBusy(false) }
  }
  const state = !status ? 'computerUseChecking' : !status.supported ? 'computerUseUnsupported'
    : !status.installed ? 'computerUseMissing' : !status.enabled ? 'computerUseDisabled' : status.readiness === 'busy' ? 'cuaControlWaiting' : status.readiness === 'unavailable' ? 'cuaControlUnavailable' : 'computerUseReady'
  return <>
    <PluginListItem pluginId="computer-use" title={t('computerUseTitle')}
      summary={t('computerUseSummary')} onOpen={() => setOpen(true)} busy={busy || !status}
      useDisabled={!status?.supported || !status?.installed}
      removeDisabled={!status?.enabled && (!status?.supported || !status?.installed)}
      onUse={() => { void (async () => {
        if (!status?.enabled && !await toggle()) { setOpen(true); return }
        await usePluginNow('computer-use')
      })() }}
      onRemove={() => { void toggle().then(ok => { if (!ok) setOpen(true) }) }}
      removeLabel={t(status?.enabled ? 'computerUseDisable' : 'computerUseEnable')} />
    {permissionsOpen && <CuaPermissionsDialog onClose={() => setPermissionsOpen(false)} />}
    {open ? createPortal(<PluginDialog pluginId="computer-use" title={t('computerUseTitle')}
      summary={t('computerUseSummary')} onClose={() => { setOpen(false) }}>
    <PluginDescription copyKey="computerUse" />
    {window.dsGui.platform === 'darwin' && <button type="button" onClick={() => setPermissionsOpen(true)} className="mt-4 rounded-lg border border-ds-border px-3 py-2 text-sm text-ds-ink hover:bg-ds-hover">{t('cuaPermissionTitle')}</button>}
    <p role="status" className="mt-5 text-sm text-ds-muted">{t(state)}</p>
    {status?.supported && !status.installed ? <p className="mt-2 text-sm text-ds-muted">{t('computerUseInstallHint')}</p> : null}
    {applied ? <p className="mt-2 text-sm text-ds-muted">{t('computerUseApplying')}</p> : null}
    {error ? <p role="alert" className="mt-2 text-sm text-ds-danger">{t('computerUseError')}</p> : null}
    {status?.installed && window.dsGui.platform === 'darwin' ? <CuaApprovedApps /> : null}
    <div className="mt-6 flex items-center justify-between border-t border-ds-border pt-4">
      <span className="text-xs text-ds-muted">{t('computerUseBuiltin')}</span>
    </div>
    <button type="button" disabled={busy} onClick={() => void refresh()} className="mt-3 text-sm text-ds-muted disabled:opacity-40">{t('computerUseRefresh')}</button>
    </PluginDialog>, document.body) : null}
  </>
}
