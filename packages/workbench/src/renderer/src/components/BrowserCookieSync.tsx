import { useEffect, useLayoutEffect, useRef, useState, type ReactElement } from 'react'
import { X, Globe2 } from 'lucide-react'
import { useLightDismiss } from '../hooks/use-light-dismiss'
import { useTranslation } from 'react-i18next'
import { browserRequest } from './BrowserWorkspace'
import { confirmAsync } from '../lib/confirm-dialog'

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
type Site = { site: string; count: number; sensitive: boolean }

export function BrowserCookieSync({ threadId, state, generation, agentBusy = false, manage, anchor, onOpen, onClose }: {
  threadId: string; state?: CookieSyncState; generation?: number; agentBusy?: boolean; manage: boolean; anchor?: DOMRect | null; onOpen: (anchor?: DOMRect) => void; onClose: () => void
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
  // Sites whose sign-ins mirror Chrome; the picker edits a draft of them.
  const [selected, setSelected] = useState<string[]>([])
  const [sites, setSites] = useState<Site[] | null>(null)
  const [sitesError, setSitesError] = useState<'' | 'permission' | 'unavailable'>('')
  const [sitesAttempt, setSitesAttempt] = useState(0)
  const [chosen, setChosen] = useState<Set<string>>(new Set())
  const [changing, setChanging] = useState(false)
  const [query, setQuery] = useState('')
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
    void browserRequest<CookieSyncState & { profiles: Source[]; selected_sites?: string[] }>(threadId, '/cookie-sync').then(next => {
      if (disposed) return
      setCurrent(next); setSources(next.profiles ?? [])
      setHasSavedCookies(next.has_saved_cookies ?? false)
      setSelected(next.selected_sites ?? [])
      setProfile(next.profile ?? (next.profiles?.length === 1 ? next.profiles[0].id : ''))
    }).catch(() => { if (!disposed && manage) setError('browserCookieSettingsFailed') })
    return () => { disposed = true }
  }, [threadId, manage])

  const picking = sources.length > 0 && (changing || current?.consent !== 'enabled' || current.profile !== profile || !selected.length)
  useEffect(() => {
    if (!manage || !picking || !profile) return
    let disposed = false
    setSites(null); setSitesError(''); setQuery('')
    void browserRequest<{ sites: Site[]; error?: 'permission' | 'unavailable' }>(threadId, `/cookie-sync/sites?profile=${encodeURIComponent(profile)}`)
      .then(next => { if (!disposed) { if (next.error) setSitesError(next.error); else setSites(next.sites) } })
      .catch(() => { if (!disposed) setSitesError('unavailable') })
    return () => { disposed = true }
  }, [threadId, manage, picking, profile, sitesAttempt])
  useEffect(() => { if (picking) setChosen(new Set(selected)) }, [picking, selected])

  async function perform(action: string, chosenSites?: string[]): Promise<void> {
    setBusy(true); setError(''); setFeedback('')
    try {
      const next = await browserRequest<CookieSyncState>(threadId, '/cookie-sync', {
        action, ...(action === 'enable' ? { profile } : {}), ...(chosenSites ? { sites: chosenSites } : {}), generation
      })
      setCurrent(next)
      if (chosenSites) { setSelected(chosenSites); setChanging(false) }
      if (action === 'skip') { setInviteDismissed(true); onClose() }
      else {
        setFeedback(next.status)
        if (['synced', 'cleared'].includes(next.status)) onClose()
      }
    } catch { setError(action === 'clear' ? 'browserCookieClearFailed' : 'browserCookieSettingsFailed') }
    finally { setBusy(false) }
  }

  async function syncChosen(): Promise<void> {
    const list = [...chosen].sort()
    const risky = list.filter(site => sites?.some(row => row.site === site && row.sensitive))
    if (risky.length && !(await confirmAsync(t('browserCookieSensitiveConfirm', { sites: risky.join(', ') })))) return
    void perform(current?.consent === 'enabled' && current.profile === profile ? 'sync' : 'enable', list)
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
    {picking && profile ? <div className="ds-cookie-sites">
      {sitesError ? <div className="ds-cookie-description" role="alert">
        <p>{t(sitesError === 'permission' ? 'browserCookieSitesPermission' : 'browserCookieSitesFailed')}</p>
        <button type="button" className={`${button} mt-2`} onClick={() => setSitesAttempt(attempt => attempt + 1)}>{t('browserCookieSitesRetry')}</button>
      </div> : sites === null ? <p className="ds-cookie-description">{t('browserCookieSitesLoading')}</p> : (() => {
        const rows = [...sites, ...selected.filter(site => !sites.some(row => row.site === site)).map(site => ({ site, count: 0, sensitive: false }))]
        if (!rows.length) return <p className="ds-cookie-description">{t('browserCookieSitesEmpty')}</p>
        const needle = query.trim().toLowerCase()
        const visible = rows.filter(row => row.site.includes(needle))
        const option = (row: Site): ReactElement => <label key={row.site} className="ds-cookie-site">
          <input type="checkbox" checked={chosen.has(row.site)} disabled={busy} onChange={() => setChosen(previous => {
            const next = new Set(previous)
            if (!next.delete(row.site)) next.add(row.site)
            return next
          })} />
          <span>{row.site}</span><span className="ds-cookie-site-count">{row.count}</span>
        </label>
        const sensitive = visible.filter(row => row.sensitive)
        // Select all covers the visible ordinary sites; sensitive ones stay an explicit choice.
        const ordinary = visible.filter(row => !row.sensitive)
        const allChosen = ordinary.length > 0 && ordinary.every(row => chosen.has(row.site))
        const someChosen = ordinary.some(row => chosen.has(row.site))
        return <>
          {rows.length > 8 ? <input type="search" className="ds-cookie-search" aria-label={t('browserCookieSitesSearch')} placeholder={t('browserCookieSitesSearch')} value={query} onChange={event => setQuery(event.target.value)} /> : null}
          <div className="ds-cookie-site-list" role="group" aria-label={t('browserCookieSitesLabel')}>
            {ordinary.length > 1 ? <label className="ds-cookie-site ds-cookie-site-all">
              <input type="checkbox" checked={allChosen} disabled={busy}
                ref={element => { if (element) element.indeterminate = someChosen && !allChosen }}
                onChange={() => setChosen(previous => {
                  const next = new Set(previous)
                  for (const row of ordinary) {
                    if (allChosen) next.delete(row.site)
                    else next.add(row.site)
                  }
                  return next
                })} />
              <span>{t(sensitive.length ? 'browserCookieSelectAllSafe' : 'browserCookieSelectAll')}</span>
              <span className="ds-cookie-site-count">{ordinary.length}</span>
            </label> : null}
            {ordinary.map(option)}
            {sensitive.length ? <><p className="ds-cookie-site-group">{t('browserCookieSitesSensitive')}</p>{sensitive.map(option)}</> : null}
          </div>
        </>
      })()}
    </div> : null}
    {!picking && selected.length ? <p className="ds-cookie-description">{t('browserCookieSelected', { count: selected.length, sites: selected.slice(0, 3).join(', ') + (selected.length > 3 ? '…' : '') })}</p> : null}
    {agentBusy && sources.length ? <p className="ds-cookie-description">{t('browserCookieAgentBusy')}</p> : null}
    <div className="flex flex-wrap gap-2">
      {sources.length && picking ? <button type="button" className="ds-cookie-primary" disabled={busy || agentBusy || current.status === 'syncing' || !profile || sites === null || (!chosen.size && !selected.length)}
        onClick={syncChosen}>
        {t(busy || current.status === 'syncing' ? 'browserCookieSyncing' : chosen.size ? 'browserCookieEnable' : 'browserCookieEnableEmpty', { count: chosen.size })}
      </button> : null}
      {sources.length && !picking ? <>
        <button type="button" className="ds-cookie-primary" disabled={busy || agentBusy || current.status === 'syncing'}
          onClick={() => void perform('sync')}>{t(busy || current.status === 'syncing' ? 'browserCookieSyncing' : 'browserCookieResync')}</button>
        <button type="button" className={button} disabled={busy} onClick={() => setChanging(true)}>{t('browserCookieChangeSites')}</button>
      </> : null}
      {changing ? <button type="button" className={button} disabled={busy} onClick={() => setChanging(false)}>{t('browserCookieKeepSites')}</button> : null}
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
        onClick={() => { void confirmAsync(t('browserCookieClearConfirm'), { destructive: true }).then((ok) => { if (ok) void perform('clear') }) }}>{t('browserCookieClear')}</button> : null}
    </div>
    </details>
    {error ? <p role="alert" className="mt-2 text-red-600">{t(error)}</p> : null}
    </div>
  </section>
  return content
}
