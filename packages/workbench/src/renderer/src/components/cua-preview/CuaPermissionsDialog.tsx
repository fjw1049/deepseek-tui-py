import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import { claimScreenPermissionPrompt, type ScreenPermission } from './screen-permission-prompt'
import { X } from 'lucide-react'
import { useModalFocus } from '../../hooks/use-modal-focus'

type Permission = { id: 'screen' | 'accessibility'; name: string; path: string }

/** System switches remain user-owned; opening Settings never counts as granting access. */
export function CuaPermissionsDialog({ onClose }: { onClose: () => void }): React.JSX.Element {
  const { t } = useTranslation('common')
  const ref = useRef<HTMLDivElement>(null)
  const titleId = useId()
  const alive = useRef(true)
  const checking = useRef(false)
  const [screen, setScreen] = useState<ScreenPermission | null>(null)
  const [entries, setEntries] = useState<Permission[]>([])
  const [error, setError] = useState(false)
  const [listError, setListError] = useState(false)
  const [opening, setOpening] = useState<string | null>(null)
  useModalFocus(true, ref, onClose)

  const refresh = useCallback(async () => {
    if (checking.current) return
    checking.current = true
    try {
      const value = await window.dsGui.getCuaScreenPermission()
      if (alive.current) {
        claimScreenPermissionPrompt(value)
        setScreen(value); setError(false)
        if (value.status === 'granted') window.dispatchEvent(new Event('cua-permission-recheck'))
      }
    } catch { if (alive.current) setError(true) }
    finally { checking.current = false }
  }, [])
  useEffect(() => {
    alive.current = true
    void refresh()
    window.addEventListener('focus', refresh)
    return () => { alive.current = false; window.removeEventListener('focus', refresh) }
  }, [refresh])
  const refreshRuntime = useCallback(async () => {
    try {
      const response = await window.dsGui.runtimeRequest('/v1/cua/permissions', 'GET')
      if (!response.ok) throw new Error('permissions unavailable')
      const list = JSON.parse(response.body).permissions
      if (!Array.isArray(list)) throw new Error('invalid permissions')
      const valid = list.filter((p: Permission | null) => p &&
        (p.id === 'screen' || p.id === 'accessibility') && typeof p.name === 'string' && typeof p.path === 'string')
      if (alive.current) { setEntries(valid); setListError(valid.length === 0) }
    } catch { if (alive.current) setListError(true) }
  }, [])
  useEffect(() => { void refreshRuntime() }, [refreshRuntime])

  const open = async (entry?: Permission): Promise<void> => {
    setOpening(entry?.id ?? 'preview'); setError(false)
    try {
      if (entry) {
        const response = await window.dsGui.runtimeRequest('/v1/cua/permissions/open', 'POST', JSON.stringify({ id: entry.id, path: entry.path }))
        if (!response.ok) throw new Error('settings unavailable')
      } else {
        await window.dsGui.openScreenCaptureSettings()
        await refresh()
      }
    } catch { if (alive.current) setError(true) }
    finally { if (alive.current) setOpening(null) }
  }
  const button = 'shrink-0 rounded-lg border border-ds-border bg-ds-card px-3 py-1.5 text-xs text-ds-ink hover:bg-ds-hover disabled:opacity-40'
  return createPortal(<div className="ds-no-drag fixed inset-0 z-[100] flex items-center justify-center bg-black/30 p-5" onClick={e => { if (e.target === e.currentTarget) onClose() }}>
    <div ref={ref} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}
      className="relative max-h-[85vh] w-full max-w-sm overflow-y-auto rounded-2xl border border-ds-border bg-ds-card p-4 text-ds-ink shadow-panel">
      <button type="button" onClick={onClose} aria-label={t('pluginCloseDetail')} className="absolute right-3 top-3 rounded-lg p-2 text-ds-muted hover:bg-ds-hover"><X className="h-4 w-4" /></button>
      <h2 id={titleId} className="pr-8 text-lg font-semibold">{t('cuaPermissionTitle')}</h2>
      <section className="mt-5 rounded-xl border border-ds-border p-3">
        <h3 className="text-sm font-medium">{t('cuaPermissionPreview')}</h3>
        <p className="mt-1 text-sm leading-relaxed text-ds-muted">{t('cuaPermissionPreviewPurpose')}</p>
        <p className="mt-2 text-sm">{screen ? t('cuaPermissionApp', { app: screen.appName }) : t('computerUseChecking')}</p>
        <div className="mt-3 flex items-center justify-between gap-3">
          <span role="status" className="text-xs text-ds-muted">{t(!screen ? 'computerUseChecking' : screen.status === 'granted' ? 'cuaPermissionGranted' : screen.status === 'restricted' ? 'cuaPermissionRestricted' : screen.status === 'unsupported' ? 'cuaPermissionUnsupported' : 'cuaPermissionNeeded')}</span>
          {screen?.status !== 'granted' && screen?.status !== 'unsupported' && <button type="button" className={button} disabled={opening !== null || !screen} onClick={() => void open()}>{t(screen?.status === 'restricted' ? 'cuaPermissionView' : 'cuaPermissionOpen')}</button>}
        </div>
      </section>
      {entries.length > 0 && <section className="mt-4">
        <h3 className="text-sm font-medium">{t('cuaPermissionRuntime')}</h3>
        {entries.map(entry => <div key={`${entry.id}:${entry.path}`} className="mt-3 flex items-center justify-between gap-3 rounded-xl border border-ds-border p-3">
          <div className="min-w-0"><p className="text-sm">{t(entry.id === 'screen' ? 'cuaPermissionScreen' : 'cuaPermissionAccessibility')}</p><p className="mt-1 text-xs leading-relaxed text-ds-muted">{t(entry.id === 'screen' ? 'cuaPermissionRuntimeScreenPurpose' : 'cuaPermissionAccessibilityPurpose')}</p><p className="mt-2 break-words text-xs">{t('cuaPermissionApp', { app: entry.name })}</p></div>
          <button type="button" className={button} disabled={opening !== null} onClick={() => void open(entry)}>{t('cuaPermissionView')}</button>
        </div>)}
      </section>}
      {listError && <p className="mt-3 text-xs text-ds-muted">{t('cuaPermissionListError')}</p>}
      {error && <p role="alert" className="mt-3 text-sm text-ds-danger">{t(typeof window.dsGui.getCuaScreenPermission === 'function' ? 'cuaPermissionError' : 'cuaPermissionRestart')}</p>}
      <div className="mt-5 flex justify-end gap-2">
        <button type="button" className={button} onClick={() => { void refresh(); void refreshRuntime() }}>{t('cuaPermissionCheck')}</button>
        <button type="button" className="rounded-lg bg-ds-ink px-3 py-1.5 text-sm text-ds-card" onClick={onClose}>{t('cuaPermissionBack')}</button>
      </div>
    </div>
  </div>, document.body)
}
