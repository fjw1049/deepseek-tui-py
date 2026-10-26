import { CuaApprovedApps } from '../cua-preview/CuaApprovedApps'
import { CuaPreviewPermission } from './CuaPreviewPermission'
import { useEffect, useState, useSyncExternalStore } from 'react'
import { useTranslation } from 'react-i18next'
import type { AppSettingsPatch, AppSettingsV1 } from '@shared/app-settings'
import { settingsToolbarButtonClass } from './SettingsActionToolbar'
import { SettingsToggle } from './SettingsToggle'
import { getCuaSettingsData, type PrivacyEntry } from '../../lib/cua-settings-data'

/** macOS grants belong to the runtime's own signed apps; name them and open their panes. */
function SystemPermissions({ showPreview }: { showPreview: boolean }): React.JSX.Element {
  const { t } = useTranslation('settings')
  const resource = getCuaSettingsData().permissions
  const { value: entries, failed } = useSyncExternalStore(resource.subscribe, resource.getSnapshot)
  const [opening, setOpening] = useState<string[]>([])
  const [openFailed, setOpenFailed] = useState(false)
  useEffect(() => { void resource.load() }, [resource])
  const open = async (entry: PrivacyEntry): Promise<void> => {
    setOpening(current => [...current, entry.path]); setOpenFailed(false)
    let timer: ReturnType<typeof setTimeout> | undefined
    try {
      const response = await Promise.race([
        window.dsGui.runtimeRequest('/v1/cua/permissions/open', 'POST', JSON.stringify({ id: entry.id })),
        new Promise<never>((_, reject) => { timer = setTimeout(() => reject(new Error('Settings request timed out')), 10_000) })
      ])
      if (!response.ok) throw new Error('Settings unavailable')
    } catch { setOpenFailed(true) }
    finally {
      clearTimeout(timer)
      setOpening(current => current.filter(path => path !== entry.path))
    }
  }
  return <section className="ds-content-card rounded-2xl">
    <div className="border-b border-ds-border-muted px-5 py-3">
      <h2 className="text-[16px] font-semibold text-ds-ink">{t('cuaSystemPermissions')}</h2>
      <p className="mt-1 text-[13px] leading-5 text-ds-muted">{t('cuaPermissionsHint')}</p>
    </div>
    <div className="divide-y divide-ds-border-muted px-5">
      {showPreview && typeof window.dsGui.getCuaScreenPermission === 'function' && <CuaPreviewPermission />}
      {!entries && !failed && <div role="status" aria-live="polite" aria-label={t('cuaPermissionsLoading')}>
        {(['cuaPermissionControl', 'cuaPermissionRead'] as const).map(title => <div key={title} className="flex items-center justify-between gap-4 py-4">
          <div className="min-w-0">
            <h3 className="text-[14px] font-medium text-ds-ink">{t(title)}</h3>
            <p className="mt-1 text-[12px] leading-5 text-ds-muted">{t('cuaPermissionsLoading')}</p>
          </div>
          <span aria-hidden="true" className="h-8 w-20 shrink-0 rounded-xl bg-ds-subtle" />
        </div>)}
      </div>}
      {(failed || entries?.length === 0) && <div className="flex items-center justify-between gap-4 py-4">
        <p role="status" className="text-[13px] leading-5 text-ds-muted">{t(failed ? 'cuaPermissionsUnavailable' : 'cuaPermissionsEmpty')}</p>
        <button type="button" className={`${settingsToolbarButtonClass()} shrink-0`} onClick={() => void resource.load(true)}>{t('cuaPermissionsRetry')}</button>
      </div>}
      {entries?.map(entry => <div className="flex items-center justify-between gap-4 py-4" key={`${entry.id}:${entry.path}`}>
        <div className="min-w-0">
          <h3 className="text-[14px] font-medium text-ds-ink">{t(entry.id === 'accessibility' ? 'cuaPermissionControl' : 'cuaPermissionRead')}</h3>
          <p className="mt-1 break-words text-[12px] leading-5 text-ds-muted">{t(entry.id === 'accessibility' ? 'cuaPermissionAccessibility' : 'cuaPermissionScreen', { name: entry.name })}</p>
        </div>
        <button type="button" className={`${settingsToolbarButtonClass(opening.includes(entry.path))} shrink-0`}
          aria-label={t('cuaPermissionOpenNamed', { name: entry.name, permission: t(entry.id === 'accessibility' ? 'cuaPermissionControl' : 'cuaPermissionRead') })}
          disabled={opening.includes(entry.path)} onClick={() => void open(entry)}>
          {t(opening.includes(entry.path) ? 'cuaPermissionOpening' : 'cuaPermissionOpen')}
        </button>
      </div>)}
    </div>
    {openFailed && <p role="alert" className="px-5 pb-4 text-[13px] text-ds-danger">{t('cuaPermissionOpenFailed')}</p>}
  </section>
}

export function CuaSettingsPanel({ form, onUpdate }: {
  form: AppSettingsV1
  onUpdate: (patch: AppSettingsPatch) => void
}): React.JSX.Element {
  const { t } = useTranslation('settings')
  // Matches the runtime adapter: LCU computer use has no Windows support.
  const supported = window.dsGui?.platform === 'darwin' || window.dsGui?.platform === 'linux'
  const resource = getCuaSettingsData().config
  const config = useSyncExternalStore(resource.subscribe, resource.getSnapshot)
  const inherited = config.value ?? (config.failed ? null : undefined)
  useEffect(() => { if (supported) void resource.load() }, [supported, resource])

  if (!supported) {
    return <div className="space-y-4 text-sm text-ds-ink">
      <p className="text-sm leading-relaxed text-ds-muted">{t('cuaUnsupported')}</p>
    </div>
  }
  const enabled = form.cuaEnabled ?? inherited?.enabled
  const rows = [
    { key: 'cuaEnabled', title: 'cuaEnable', hint: 'cuaEnableHint', value: enabled },
    { key: 'cuaWindowPreview', title: 'cuaWindowPreview', hint: 'cuaWindowPreviewHint', value: form.cuaWindowPreview !== false },
    { key: 'cuaChrome', title: 'cuaChromeShort', hint: 'cuaChromeHint', value: form.cuaChrome ?? inherited?.chrome },
    { key: 'cuaAutoAllowApps', title: 'cuaAutoAllowAppsShort', hint: 'cuaAutoAllowAppsSummary', value: form.cuaAutoAllowApps ?? inherited?.autoAllowApps }
  ] as const
  return <div className="space-y-6 text-sm text-ds-ink">
    <section className="ds-content-card rounded-2xl">
      <div className="divide-y divide-ds-border-muted px-2 py-1">
        {rows.map(row => <div key={row.key} className="ds-density-row flex items-center justify-between gap-6 px-4 py-5">
          <div className="min-w-0">
            <div className="text-[14px] font-semibold">{t(row.title)}</div>
            <p className="mt-0.5 max-w-md text-[13px] leading-relaxed text-ds-muted">{t(row.hint)}</p>
            {row.value === undefined && <p role="status" className="mt-1 text-xs text-ds-muted">{t(inherited === null ? 'cuaInheritedUnknown' : 'cuaLoading')}</p>}
            {row.key === 'cuaAutoAllowApps' && <details className="mt-2 max-w-md text-[13px] leading-relaxed text-ds-muted">
              <summary className="cursor-pointer hover:text-ds-ink">{t('cuaAccessDetails')}</summary>
              <p className="mt-2">{t('cuaAutoAllowAppsHint')}</p>
            </details>}
          </div>
          <SettingsToggle label={t(row.title)} checked={row.value === true}
            disabled={row.value === undefined || (row.key !== 'cuaEnabled' && enabled !== true)}
            onChange={value => onUpdate({ [row.key]: value })} />
        </div>)}
      </div>
    </section>
    {window.dsGui?.platform === 'darwin' && enabled !== false ? <SystemPermissions showPreview={form.cuaWindowPreview !== false} /> : null}
    {window.dsGui?.platform === 'darwin' && <>
      <CuaApprovedApps />
      {(form.cuaAutoAllowApps ?? inherited?.autoAllowApps) === true && <p className="text-[13px] leading-relaxed text-ds-muted">{t('cuaAutoAllowAppsRevokeHint')}</p>}
    </>}
  </div>
}
