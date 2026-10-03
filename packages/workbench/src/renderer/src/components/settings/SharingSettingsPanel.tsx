import { reportActionError } from '../../store/feedback-store'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { sharingRequest, type ShareSettings } from '../../lib/session-sharing'

/** One-time self-hosted deployment settings, deliberately outside the sharing flow. */
export function SharingSettingsPanel() {
  const { t } = useTranslation('common')
  const [service, setService] = useState('')
  const [key, setKey] = useState('')
  const [loaded, setLoaded] = useState(false)
  const [pending, setPending] = useState(false)
  const [notice, setNotice] = useState('')
  const field = 'mt-1 w-full rounded-lg border border-ds-border bg-ds-elevated px-3 py-2 text-sm'
  const load = async () => {
    if (loaded || pending) return
    setPending(true)
    try { const config = await sharingRequest<ShareSettings>('settings', 'GET'); setService(config.service_url); setLoaded(true) }
    catch (error) { reportActionError(error) }
    finally { setPending(false) }
  }
  return <details className="mt-5 rounded-xl border border-ds-border p-4 text-ds-muted" onToggle={e => { if (e.currentTarget.open) void load() }}>
    <summary className="cursor-pointer text-sm">{t('sharing.adminSettings')}</summary>
    <p className="my-3 text-sm">{t('sharing.adminHint')}</p>
    <label className="block text-sm">{t('sharing.service')}<input className={field} disabled={pending} value={service} onChange={e => setService(e.target.value)} /></label>
    <label className="mt-3 block text-sm">{t('sharing.key')}<input className={field} type="password" autoComplete="off" disabled={pending} value={key} placeholder={t('sharing.keySaved')} onChange={e => setKey(e.target.value)} /></label>
    <button disabled={pending || !loaded || !service.trim()} className="mt-3 rounded-lg border border-ds-border px-3 py-2 text-sm disabled:opacity-40" onClick={() => {
      setPending(true); setNotice('')
      void sharingRequest('settings', 'PUT', { service_url: service, ...(key ? { upload_key: key } : {}) }).then(() => { setKey(''); setNotice(t('sharing.saved')) }).catch(error => reportActionError(error)).finally(() => setPending(false))
    }}>{t('sharing.save')}</button>
    {notice && <p role="status" className="mt-2 text-sm">{notice}</p>}
  </details>
}
