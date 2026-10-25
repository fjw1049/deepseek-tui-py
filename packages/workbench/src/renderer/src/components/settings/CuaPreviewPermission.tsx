import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { ScreenPermission } from '../cua-preview/screen-permission-prompt'
import { settingsToolbarButtonClass } from './SettingsActionToolbar'

/** The preview is captured by this app, separately from the control component. */
export function CuaPreviewPermission(): React.JSX.Element {
  const { t } = useTranslation('settings')
  const [permission, setPermission] = useState<ScreenPermission | null>(null)
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState(false)
  const refresh = useCallback(async () => {
    const value = await window.dsGui.getCuaScreenPermission()
    setPermission(value)
    if (value.status === 'granted') window.dispatchEvent(new Event('cua-permission-recheck'))
  }, [])
  useEffect(() => {
    const check = (): void => { void refresh().catch(() => setFailed(true)) }
    check()
    window.addEventListener('focus', check)
    return () => window.removeEventListener('focus', check)
  }, [refresh])
  const request = async (): Promise<void> => {
    setBusy(true); setFailed(false)
    let timer: ReturnType<typeof setTimeout> | undefined
    try {
      await Promise.race([
        window.dsGui.openScreenCaptureSettings(),
        new Promise<never>((_, reject) => { timer = setTimeout(() => reject(new Error('Permission request timed out')), 15_000) })
      ])
      await refresh()
    } catch { setFailed(true) }
    finally { clearTimeout(timer); setBusy(false) }
  }
  return <div className="py-4">
    <div className="flex items-center justify-between gap-4">
      <div className="min-w-0">
        <h3 className="text-[14px] font-medium text-ds-ink">{t('cuaPreviewPermissionTitle')}</h3>
        <p className="mt-1 break-words text-[12px] leading-5 text-ds-muted">{permission ? t('cuaPermissionScreen', { name: permission.appName }) : t('cuaPermissionsLoading')}</p>
        <p className="mt-1 text-[12px] leading-5 text-ds-muted">{t('cuaPreviewPermissionHint')}</p>
      </div>
      {permission?.status === 'granted'
        ? <span role="status" className="shrink-0 text-[13px] text-ds-muted">{t('cuaPreviewPermissionGranted')}</span>
        : <button type="button" disabled={busy} className={`${settingsToolbarButtonClass(busy)} shrink-0`} onClick={() => void request()}>{t(busy ? 'cuaPermissionOpening' : 'cuaPreviewPermissionRequest')}</button>}
    </div>
    {failed && <p role="alert" className="mt-2 text-[13px] text-ds-danger">{t('cuaPreviewPermissionFailed')}</p>}
  </div>
}
