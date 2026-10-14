import { useEffect, useState, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { browserRequest } from './BrowserWorkspace'

export type CookieSyncState = {
  consent: 'pending' | 'enabled' | 'skipped' | 'disabled'
  profile: string | null
  status: string
  count: number
  skipped: number
  domains?: number
}
type Source = { id: string; name: string }

export function BrowserCookieSync({ threadId, state, generation, manage, onClose }: {
  threadId: string; state?: CookieSyncState; generation?: number; manage: boolean; onClose: () => void
}): ReactElement | null {
  const { t } = useTranslation('common')
  const [current, setCurrent] = useState<CookieSyncState | null>(state ?? null)
  const [sources, setSources] = useState<Source[]>([])
  const [profile, setProfile] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [dismissed, setDismissed] = useState('')
  useEffect(() => { if (state) setCurrent(state) }, [state])
  useEffect(() => {
    let disposed = false
    void browserRequest<CookieSyncState & { profiles: Source[] }>(threadId, '/cookie-sync').then(next => {
      if (disposed) return
      setCurrent(next); setSources(next.profiles ?? [])
      setProfile(next.profile ?? (next.profiles?.length === 1 ? next.profiles[0].id : ''))
    }).catch(() => { if (!disposed && manage) setError('browserCookieSettingsFailed') })
    return () => { disposed = true }
  }, [threadId, manage])

  async function perform(action: string): Promise<void> {
    setBusy(true); setError(''); setDismissed('')
    try {
      const next = await browserRequest<CookieSyncState>(threadId, '/cookie-sync', {
        action, ...(action === 'enable' ? { profile } : {}), generation
      })
      setCurrent(next)
      if (action === 'skip') onClose()
    } catch { setError(action === 'clear' ? 'browserCookieClearFailed' : 'browserCookieSettingsFailed') }
    finally { setBusy(false) }
  }

  if (!current) return null
  const attention = ['syncing', 'synced', 'empty', 'unavailable', 'partial', 'save_failed', 'apply_failed'].includes(current.status)
  if (!manage && current.consent !== 'pending' && !busy && (!attention || dismissed === current.status)) return null
  const button = 'rounded-md border border-ds-border px-3 py-1.5 text-xs disabled:opacity-40'
  return <section className="border-b border-ds-border bg-ds-subtle px-3 py-3 text-xs" aria-label={t('browserCookieTitle')}>
    <div className="mb-1 flex items-center justify-between gap-2">
      <strong>{t('browserCookieTitle')}</strong>
      {current.consent !== 'pending' ? <button type="button" className={button} disabled={busy}
        onClick={() => { setDismissed(current.status); onClose() }}>{t('browserCookieDismiss')}</button> : null}
    </div>
    <p className="mb-2 text-ds-muted">{t(sources.length ? 'browserCookieHint' : 'browserCookieNoChrome')}</p>
    {sources.length > 1 ? <label className="mb-2 block">{t('browserCookieSource')}
      <select className="ml-2 rounded border border-ds-border bg-ds-surface p-1" value={profile} disabled={busy}
        onChange={event => setProfile(event.target.value)}>
        <option value="">{t('browserCookieChooseSource')}</option>
        {sources.map(source => <option key={source.id} value={source.id}>{source.name}</option>)}
      </select>
    </label> : null}
    <div className="flex flex-wrap gap-2">
      {sources.length ? <button type="button" className={button} disabled={busy || !profile}
        onClick={() => void perform(current.consent === 'enabled' && current.profile === profile ? 'sync' : 'enable')}>
        {t(busy || current.status === 'syncing' ? 'browserCookieSyncing' : current.consent === 'enabled' ? 'browserCookieResync' : 'browserCookieEnable')}
      </button> : null}
      {current.consent === 'pending' ? <button type="button" className={button} disabled={busy}
        onClick={() => void perform('skip')}>{t(sources.length ? 'browserCookieSkip' : 'browserCookieContinue')}</button> : null}
      {manage && current.consent === 'enabled' ? <button type="button" className={button} disabled={busy}
        onClick={() => void perform('disable')}>{t('browserCookieDisable')}</button> : null}
      {manage ? <button type="button" className={button} disabled={busy}
        onClick={() => { if (window.confirm(t('browserCookieClearConfirm'))) void perform('clear') }}>{t('browserCookieClear')}</button> : null}
    </div>
    <p role="status" className="mt-2 text-ds-muted">{t(`browserCookieStatus_${busy ? 'syncing' : current.status}`, { count: current.count, skipped: current.skipped, domains: current.domains ?? 0 })}</p>
    {error ? <p role="alert" className="mt-2 text-red-600">{t(error)}</p> : null}
  </section>
}
