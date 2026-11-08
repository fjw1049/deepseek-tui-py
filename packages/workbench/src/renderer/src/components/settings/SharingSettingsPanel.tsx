import { reportActionError } from '../../store/feedback-store'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronDown } from 'lucide-react'
import { settingsToolbarButtonClass } from './SettingsActionToolbar'
import { sharingRequest, type ShareSettings } from '../../lib/session-sharing'

/** One-time self-hosted deployment settings, deliberately outside the sharing flow. */
export function SharingSettingsPanel() {
  const { t } = useTranslation('common')
  const [service, setService] = useState('')
  const [key, setKey] = useState('')
  const [loaded, setLoaded] = useState(false)
  const [pending, setPending] = useState(false)
  const [notice, setNotice] = useState('')
  const field = 'mt-1.5 w-full min-w-0 rounded-xl border border-ds-border bg-ds-card px-3 py-2 text-[14px] text-ds-ink shadow-sm focus:border-accent/40 focus:outline-none focus:ring-1 focus:ring-accent/30 disabled:opacity-55'
  const label = 'block text-[13px] font-medium text-ds-ink'
  const load = async () => {
    if (loaded || pending) return
    setPending(true)
    try { const config = await sharingRequest<ShareSettings>('settings', 'GET'); setService(config.service_url); setLoaded(true) }
    catch (error) { reportActionError(error) }
    finally { setPending(false) }
  }
  const saveDisabled = pending || !loaded || !service.trim()
  return <details className="ds-content-card group mt-6 rounded-2xl" onToggle={e => { if (e.currentTarget.open) void load() }}>
    <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-5 py-3 text-[14px] font-semibold text-ds-ink [&::-webkit-details-marker]:hidden">
      {t('sharing.adminSettings')}
      <ChevronDown className="h-4 w-4 shrink-0 text-ds-faint transition-transform group-open:rotate-180" strokeWidth={1.75} />
    </summary>
    <div className="space-y-4 border-t border-ds-border-muted px-5 py-4">
    <p className="text-[13px] leading-relaxed text-ds-muted">{t('sharing.adminHint')}</p>
    <label className={label}>{t('sharing.service')}<input className={field} disabled={pending} value={service} onChange={e => setService(e.target.value)} /></label>
    <label className={label}>{t('sharing.key')}<input className={field} type="password" autoComplete="off" disabled={pending} value={key} placeholder={t('sharing.keySaved')} onChange={e => setKey(e.target.value)} /></label>
    <div className="flex items-center justify-end gap-3">
    {notice && <p role="status" className="text-[12.5px] text-ds-muted">{notice}</p>}
    <button type="button" disabled={saveDisabled} className={settingsToolbarButtonClass(saveDisabled)} onClick={() => {
      setPending(true); setNotice('')
      void sharingRequest('settings', 'PUT', { service_url: service, ...(key ? { upload_key: key } : {}) }).then(() => { setKey(''); setNotice(t('sharing.saved')) }).catch(error => reportActionError(error)).finally(() => setPending(false))
    }}>{t('sharing.save')}</button>
    </div>
    </div>
  </details>
}
