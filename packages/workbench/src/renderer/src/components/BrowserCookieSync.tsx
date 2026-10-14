import { useEffect, useLayoutEffect, useRef, useState, type ReactElement } from 'react'
import { X, Globe2 } from 'lucide-react'
import { useLightDismiss } from '../hooks/use-light-dismiss'
import { useTranslation } from 'react-i18next'
import { browserRequest } from './BrowserWorkspace'

export type CookieSyncState = {
  consent: 'pending' | 'enabled' | 'skipped' | 'disabled'
  profile: string | null
  status: string
  count: number
  skipped: number
  has_saved_cookies?: boolean
  domains?: number
}
const inviteSeenKey = 'browser-cookie-invite-seen'

type Source = { id: string; name: string }

export function BrowserCookieSync({ threadId, state, generation, manage, anchor, onOpen, onClose }: {
  threadId: string; state?: CookieSyncState; generation?: number; manage: boolean; anchor?: DOMRect | null; onOpen: (anchor?: DOMRect) => void; onClose: () => void
}): ReactElement | null {
  const { t } = useTranslation('common')
  const [current, setCurrent] = useState<CookieSyncState | null>(state ?? null)
  const [sources, setSources] = useState<Source[]>([])
  const [profile, setProfile] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [feedback, setFeedback] = useState('')
  const [inviteDismissed, setInviteDismissed] = useState(() => {
    try { return localStorage.getItem(inviteSeenKey) === '1' } catch { return false }
  })
  const [hasSavedCookies, setHasSavedCookies] = useState(false)
  const showInvite = !manage && !inviteDismissed && !hasSavedCookies && current?.consent === 'pending' && current.count === 0 && sources.length > 0 && !busy && !feedback
  useEffect(() => {
    if (showInvite) {
      try { localStorage.setItem(inviteSeenKey, '1') } catch { /* Keep browsing if storage is unavailable. */ }
    }
  }, [showInvite])
  const panel = useRef<HTMLElement>(null)
  const [position, setPosition] = useState({ left: 12, top: 12 })
  useLightDismiss({ open: manage, refs: [panel], onDismiss: () => { setInviteDismissed(true); onClose() } })
  useLayoutEffect(() => {
    if (!manage || !anchor || !panel.current) return
    const place = () => {
      const width = panel.current!.offsetWidth
      const height = panel.current!.offsetHeight
      const container = panel.current!.offsetParent as HTMLElement | null
      const bounds = container?.getBoundingClientRect()
      const availableWidth = container?.clientWidth || window.innerWidth
      const availableHeight = container?.clientHeight || window.innerHeight
      const scaleX = bounds?.width ? availableWidth / bounds.width : 1
      const scaleY = bounds?.height ? availableHeight / bounds.height : 1
      const left = (anchor.right - (bounds?.left ?? 0)) * scaleX - width
      const top = (anchor.bottom - (bounds?.top ?? 0)) * scaleY + 8
      setPosition({
        left: Math.max(12, Math.min(left, availableWidth - width - 12)),
        top: Math.max(12, Math.min(top, availableHeight - height - 12))
      })
    }
    place()
    const observer = new ResizeObserver(place)
    observer.observe(panel.current)
    window.addEventListener('resize', place)
    return () => { observer.disconnect(); window.removeEventListener('resize', place) }
  }, [manage, anchor, current !== null])
  const loaded = current !== null
  const closeButton = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (!manage) return
    const previous = document.activeElement as HTMLElement | null
    closeButton.current?.focus()
    return () => { if (previous?.isConnected && previous !== document.body) previous.focus() }
  }, [manage, loaded])
  useEffect(() => {
    if (!['synced', 'cleared'].includes(feedback)) return
    const timer = window.setTimeout(() => setFeedback(''), 4000)
    return () => window.clearTimeout(timer)
  }, [feedback])
  useEffect(() => { if (state) setCurrent(state) }, [state])
  useEffect(() => {
    let disposed = false
    void browserRequest<CookieSyncState & { profiles: Source[] }>(threadId, '/cookie-sync').then(next => {
      if (disposed) return
      setCurrent(next); setSources(next.profiles ?? [])
      setHasSavedCookies(next.has_saved_cookies ?? false)
      setProfile(next.profile ?? (next.profiles?.length === 1 ? next.profiles[0].id : ''))
    }).catch(() => { if (!disposed && manage) setError('browserCookieSettingsFailed') })
    return () => { disposed = true }
  }, [threadId, manage])

  async function perform(action: string): Promise<void> {
    setBusy(true); setError(''); setFeedback('')
    try {
      const next = await browserRequest<CookieSyncState>(threadId, '/cookie-sync', {
        action, ...(action === 'enable' ? { profile } : {}), generation
      })
      setCurrent(next)
      if (action === 'skip') { setInviteDismissed(true); onClose() }
      else {
        setFeedback(next.status)
        if (['synced', 'cleared'].includes(next.status)) onClose()
      }
    } catch { setError(action === 'clear' ? 'browserCookieClearFailed' : 'browserCookieSettingsFailed') }
    finally { setBusy(false) }
  }

  if (!current) return null
  const button = 'rounded-md border border-ds-border px-3 py-1.5 text-xs disabled:opacity-40'
  if (!manage) {
    if (showInvite) return <div className="ds-browser-cookie-toast ds-browser-cookie-invite" role="status">
      <span>{t('browserCookieInvite')}</span>
      <button type="button" onClick={event => onOpen(event.currentTarget.getBoundingClientRect())}>{t('browserCookieSetup')}</button>
      <button type="button" disabled={busy} onClick={() => void perform('skip')}>{t('browserCookieSkip')}</button>
      {error ? <span role="alert">{t(error)}</span> : null}
    </div>
    if (!feedback && !busy && !error) return null
    return <div className="ds-browser-cookie-toast" role="status">
      <span>{t(error || `browserCookieFeedback_${busy ? 'syncing' : feedback}`)}</span>
      <button type="button" onClick={event => onOpen(event.currentTarget.getBoundingClientRect())}>{t('browserCookieDetails')}</button>
      {!busy ? <button type="button" onClick={() => { setFeedback(''); setError('') }}>{t('browserCookieDismiss')}</button> : null}
    </div>
  }
  const content = <section ref={panel} style={anchor ? position : undefined} className="ds-browser-cookie-settings" role="dialog" aria-label={t('browserCookieTitle')}
    onKeyDown={event => {
      if (event.key === 'Escape') { event.stopPropagation(); setInviteDismissed(true); onClose() }
    }}>
    <header>
      <strong><Globe2 size={16} />{t('browserCookieManage')}</strong>
      <button ref={closeButton} type="button" className="ds-cookie-close" aria-label={t('browserCookieDismiss')} onClick={() => { setInviteDismissed(true); onClose() }}><X size={16} /></button>
    </header>
    <div className="ds-browser-cookie-settings-body">
    {!sources.length ? <p className="ds-cookie-description">{t('browserCookieNoChrome')}</p> : null}
    <p role="status" className="ds-cookie-status">{t(`browserCookieStatus_${busy ? 'syncing' : current.status}`, { count: current.count, skipped: current.skipped, domains: current.domains ?? 0 })}</p>
    {sources.length > 1 ? <label className="mb-2 block">{t('browserCookieSource')}
      <select className="ml-2 rounded border border-ds-border bg-ds-surface p-1" value={profile} disabled={busy}
        onChange={event => setProfile(event.target.value)}>
        <option value="">{t('browserCookieChooseSource')}</option>
        {sources.map(source => <option key={source.id} value={source.id}>{source.name}</option>)}
      </select>
    </label> : null}
    <div className="flex flex-wrap gap-2">
      {sources.length ? <button type="button" className="ds-cookie-primary" disabled={busy || current.status === 'syncing' || !profile}
        onClick={() => void perform(current.consent === 'enabled' && current.profile === profile ? 'sync' : 'enable')}>
        {t(busy || current.status === 'syncing' ? 'browserCookieSyncing' : current.consent === 'enabled' ? 'browserCookieResync' : 'browserCookieEnable')}
      </button> : null}
      {current.consent === 'pending' ? <button type="button" className={button} disabled={busy}
        onClick={() => void perform('skip')}>{t(sources.length ? 'browserCookieSkip' : 'browserCookieContinue')}</button> : null}
    </div>
    <details className="ds-cookie-details">
      <summary>{t('browserCookieOptions')}</summary>
      <p>{t('browserCookieHint')}</p>
      {current.count > 0 || current.skipped > 0 ? <p>{t('browserCookieCounts', { count: current.count, domains: current.domains ?? 0, skipped: current.skipped })}</p> : null}
      <div className="ds-cookie-management">
      {manage && current.consent === 'enabled' ? <button type="button" className="ds-cookie-secondary" disabled={busy}
        onClick={() => void perform('disable')}>{t('browserCookieDisable')}</button> : null}
      {manage ? <button type="button" className="ds-cookie-danger" disabled={busy}
        onClick={() => { if (window.confirm(t('browserCookieClearConfirm'))) void perform('clear') }}>{t('browserCookieClear')}</button> : null}
    </div>
    </details>
    {error ? <p role="alert" className="mt-2 text-red-600">{t(error)}</p> : null}
    </div>
  </section>
  return content
}
