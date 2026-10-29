import { AppWindow, Plug, ShieldCheck } from 'lucide-react'
import { CuaApprovedApps } from '../cua-preview/CuaApprovedApps'
import { CuaPermissionsDialog } from '../cua-preview/CuaPermissionsDialog'
import { CuaSetupChecklist } from './CuaSetupChecklist'
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
  const [module, setModule] = useState<'setup' | 'apps' | null>(null)
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
      actions={[
        { label: t('cuaSetupTitle'), icon: Plug, onClick: () => setModule('setup'), disabled: !status?.supported },
        ...(window.dsGui.platform === 'darwin' ? [
          { label: t('cuaSetupPermissions'), icon: ShieldCheck, onClick: () => setPermissionsOpen(true), disabled: !status?.installed },
          { label: t('computerUseApprovedApps'), icon: AppWindow, onClick: () => setModule('apps'), disabled: !status?.installed }
        ] : [])
      ]}
      summary={t('computerUseSummary')} onOpen={() => setOpen(true)} busy={busy || !status}
      useDisabled={!status?.supported || !status?.installed}
      removeDisabled={!status?.enabled && (!status?.supported || !status?.installed)}
      onUse={() => { void (async () => {
        if (!status?.enabled && !await toggle()) { setOpen(true); return }
        await usePluginNow('computer-use')
      })() }}
      onRemove={() => { void toggle().then(ok => { if (!ok) setOpen(true) }) }}
      removeLabel={t(status?.enabled ? 'computerUseDisable' : 'computerUseEnable')} />
    {module ? createPortal(<PluginDialog pluginId="computer-use" title={t(module === 'setup' ? 'cuaSetupTitle' : 'computerUseApprovedApps')}
      summary={t('computerUseSummary')} onClose={() => setModule(null)}>
      {module === 'setup' ? <CuaSetupChecklist onChanged={() => void refresh()} /> : <div className="mt-5"><CuaApprovedApps /></div>}
    </PluginDialog>, document.body) : null}
    {permissionsOpen && <CuaPermissionsDialog onClose={() => setPermissionsOpen(false)} />}
    {open ? createPortal(<PluginDialog pluginId="computer-use" title={t('computerUseTitle')}
      summary={t('computerUseSummary')} onClose={() => { setOpen(false) }}>
    <PluginDescription copyKey="computerUse" />
    <p role="status" className="mt-5 text-sm text-ds-muted">{t(state)}</p>
    {applied ? <p className="mt-2 text-sm text-ds-muted">{t('computerUseApplying')}</p> : null}
    {error ? <p role="alert" className="mt-2 text-sm text-ds-danger">{t('computerUseError')}</p> : null}
    <div className="mt-6 flex items-center justify-between border-t border-ds-border pt-4">
      <span className="text-xs text-ds-muted">{t('computerUseBuiltin')}</span>
    </div>
    <button type="button" disabled={busy} onClick={() => void refresh()} className="mt-3 text-sm text-ds-muted disabled:opacity-40">{t('computerUseRefresh')}</button>
    </PluginDialog>, document.body) : null}
  </>
}
