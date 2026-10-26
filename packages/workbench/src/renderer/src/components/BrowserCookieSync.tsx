import { createPortal } from 'react-dom'
import { useEffect, useLayoutEffect, useRef, useState, type ReactElement } from 'react'
import { X, Globe2, CircleCheck, ChevronDown } from 'lucide-react'
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
const inviteNeverKey = 'browser-cookie-invite-never'
// "Not now" lasts until the app restarts.
const inviteLaterKey = 'browser-cookie-invite-later'

type Source = { id: string; name: string }
type Site = { site: string; count: number; sensitive: boolean }

export function BrowserCookieSync({ threadId, state, generation, agentBusy = false, blank = false, updateRequest = 0, manage, anchor, settingsDialog = false, onOpen, onClose }: {
  threadId: string; state?: CookieSyncState; generation?: number; agentBusy?: boolean
  /** The built-in browser shows an empty new tab, where the import invitation may appear. */
  blank?: boolean
  /** Increments when the user asks to update cookies from the browser menu. */
  updateRequest?: number
  settingsDialog?: boolean
  manage: boolean; anchor?: DOMRect | null; onOpen: (anchor?: DOMRect) => void; onClose: () => void
}): ReactElement | null {
  const { t } = useTranslation('common')
  const [current, setCurrent] = useState<CookieSyncState | null>(state ?? null)
  const [sources, setSources] = useState<Source[]>([])
  const [profile, setProfile] = useState('')
  const [busy, setBusy] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [error, setError] = useState('')
  const [feedback, setFeedback] = useState('')
  const [inviteDismissed, setInviteDismissed] = useState(() => {
    try { return sessionStorage.getItem(inviteLaterKey) === '1' || localStorage.getItem(inviteNeverKey) === '1' } catch { return false }
  })
  const [hasSavedCookies, setHasSavedCookies] = useState(false)
  // Whether the built-in browser holds any cookie; null until known.
  const [nativeCookies, setNativeCookies] = useState<boolean | null>(null)
  const [nativeCheck, setNativeCheck] = useState(0)
  // Opened from the invitation: shown as a modal, and declining it counts as "Not now".
  const [fromInvite, setFromInvite] = useState(false)
  // Sites whose sign-ins mirror Chrome; the picker edits a draft of them.
  const [selected, setSelected] = useState<string[]>([])
  const [sites, setSites] = useState<Site[] | null>(null)
  const [sitesError, setSitesError] = useState<'' | 'permission' | 'unavailable'>('')
  const [sitesAttempt, setSitesAttempt] = useState(0)
  const [chosen, setChosen] = useState<Set<string>>(new Set())
  const [changing, setChanging] = useState(false)
  const [query, setQuery] = useState('')
  const showInvite = blank && !manage && !inviteDismissed && nativeCookies === false && !hasSavedCookies && current !== null && sources.length > 0 && !busy && !feedback && !error
  function dismissInvite(never = false): void {
    try {
      sessionStorage.setItem(inviteLaterKey, '1')
      if (never) localStorage.setItem(inviteNeverKey, '1')
    } catch { /* Keep browsing if storage is unavailable. */ }
    setInviteDismissed(true)
  }
  useEffect(() => {
    if (!blank) return
    let disposed = false
    // Without the desktop bridge only the app's saved cookies are known.
    void Promise.resolve(window.dsGui?.hasBrowserCookies?.() ?? false)
      .then(has => { if (!disposed) setNativeCookies(has) })
      .catch(() => { /* Unknown: stay quiet rather than nag. */ })
    return () => { disposed = true }
  }, [blank, nativeCheck])
  useEffect(() => { if (!manage) setFromInvite(false) }, [manage])
  function closePanel(): void {
    if (busy || confirming) return
    if (fromInvite) dismissInvite()
    onClose()
  }
  const panel = useRef<HTMLElement>(null)
  const [position, setPosition] = useState({ left: 12, top: 12 })
  useLightDismiss({ open: manage, refs: [panel], onDismiss: closePanel, enabled: !settingsDialog && !busy && !confirming })
  const loaded = current !== null
  useLayoutEffect(() => {
    if (!manage || !anchor || fromInvite || !panel.current) return
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
  }, [manage, anchor, fromInvite, loaded])
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
      if (action === 'clear') setHasSavedCookies(false)
      else if (next.count > 0) setHasSavedCookies(true)
      setNativeCheck(count => count + 1)
      if (chosenSites) { setSelected(chosenSites); setChanging(false) }
      if (action === 'skip') { dismissInvite(); onClose() }
      else {
        setFeedback(next.status)
        if (['synced', 'cleared'].includes(next.status)) onClose()
      }
    } catch { setError(action === 'clear' ? 'browserCookieClearFailed' : 'browserCookieSettingsFailed') }
    finally { setBusy(false) }
  }

  // A request made before this panel mounted (e.g. before the browser was hidden) is not replayed.
  const handledUpdate = useRef(updateRequest)
  useEffect(() => {
    if (updateRequest === handledUpdate.current) return
    handledUpdate.current = updateRequest
    // Configured: refresh the saved sites in place. Otherwise choose them first.
    if (current?.consent === 'enabled' && current.profile && selected.length && !agentBusy) void perform('sync')
    else onOpen()
    // Runs once per request, with the state the user saw when asking.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [updateRequest])

  async function syncChosen(): Promise<void> {
    const list = [...chosen].sort()
    const risky = list.filter(site => sites?.some(row => row.site === site && row.sensitive))
    if (risky.length) {
      setConfirming(true)
      let approved = false
      try { approved = await confirmAsync(t('browserCookieSensitiveConfirm', { sites: risky.join(', ') })) }
      finally { setConfirming(false) }
      if (!approved) return
    }
    void perform(current?.consent === 'enabled' && current.profile === profile ? 'sync' : 'enable', list)
  }

  async function clearSignIns(): Promise<void> {
    setConfirming(true)
    try {
      if (await confirmAsync(t('browserCookieClearConfirm'), { destructive: true })) await perform('clear')
    } finally { setConfirming(false) }
  }
  function modalSurface(content: ReactElement): ReactElement {
    if (settingsDialog) return createPortal(<div className="ds-no-drag fixed inset-0 z-[130] flex items-center justify-center bg-black/30 p-4"
      onMouseDown={event => { if (event.target === event.currentTarget) closePanel() }}>{content}</div>, document.body)
    return <div className="ds-browser-cookie-modal">{content}</div>
  }
  if (!current) return manage ? modalSurface(<section ref={panel} className="ds-browser-cookie-settings is-modal" role="dialog" aria-modal={settingsDialog || undefined} aria-label={t('browserCookieManage')}>
      <header><strong>{t('browserCookieManage')}</strong><button ref={closeButton} type="button" className="ds-cookie-close" disabled={busy || confirming} aria-label={t('browserCookieDismiss')} onClick={closePanel}><X size={16} /></button></header>
      <p className="ds-browser-cookie-settings-body" role={error ? 'alert' : 'status'}>{t(error || 'browserCookieStatus_syncing')}</p>
    </section>) : null
  const button = 'ds-cookie-button'
  if (!manage) {
    if (showInvite) return <div className="ds-browser-cookie-invite">
      <section className="ds-browser-cookie-invite-card" aria-labelledby="ds-cookie-invite-title">
        <span className="ds-chrome-logo is-large" aria-hidden="true" />
        <h3 id="ds-cookie-invite-title">{t('browserCookieInviteTitle')}</h3>
        <p>{t('browserCookieInviteBody')}</p>
        <ul>
          {['browserCookieInviteCookiesOnly', 'browserCookieInviteYouChoose', 'browserCookieInviteLocal'].map(key =>
            <li key={key}><CircleCheck size={15} />{t(key)}</li>)}
        </ul>
        <footer>
          <button type="button" className="ds-cookie-invite-never" onClick={() => dismissInvite(true)}>{t('browserCookieInviteNever')}</button>
          <button type="button" className="ds-cookie-invite-later" onClick={() => dismissInvite()}>{t('browserCookieInviteLater')}</button>
          <button type="button" className="ds-cookie-invite-import" onClick={event => { setFromInvite(true); onOpen(event.currentTarget.getBoundingClientRect()) }}>{t('browserCookieInviteImport')}</button>
        </footer>
      </section>
    </div>
    if (!feedback && !busy && !error) return null
    return <div className="ds-browser-cookie-toast" role="status">
      <span>{t(error || `browserCookieFeedback_${busy ? 'syncing' : feedback}`)}</span>
      <button type="button" onClick={event => onOpen(event.currentTarget.getBoundingClientRect())}>{t('browserCookieDetails')}</button>
      {!busy ? <button type="button" onClick={() => { setFeedback(''); setError('') }}>{t('browserCookieDismiss')}</button> : null}
    </div>
  }
  const modal = fromInvite || !anchor
  const content = <section ref={panel} style={anchor && !fromInvite ? position : undefined} className={`ds-browser-cookie-settings${modal ? ' is-modal' : ''}${settingsDialog ? ' is-settings-dialog' : ''}`} role="dialog" aria-modal={settingsDialog || undefined} aria-label={t(fromInvite ? 'browserCookieImportTitle' : 'browserCookieTitle')}
    onKeyDown={event => {
      if (event.key === 'Escape') { event.stopPropagation(); closePanel() }
      if (settingsDialog && event.key === 'Tab') {
        const controls = [...event.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), summary')]
          .filter(element => !element.closest('details:not([open])') || element.tagName === 'SUMMARY')
        const first = controls[0], last = controls[controls.length - 1]
        if (event.shiftKey ? document.activeElement === first : document.activeElement === last) {
          event.preventDefault(); (event.shiftKey ? last : first)?.focus()
        }
      }
    }}>
    <header>
      {fromInvite ? <strong>{t('browserCookieImportTitle')}</strong> : <strong><Globe2 size={16} />{t('browserCookieManage')}</strong>}
      <button ref={closeButton} type="button" className="ds-cookie-close" disabled={busy || confirming} aria-label={t('browserCookieDismiss')} onClick={closePanel}><X size={16} /></button>
    </header>
    <div className="ds-browser-cookie-settings-body">
    {!sources.length ? <p className="ds-cookie-description">{t('browserCookieNoChrome')}</p> : null}
    {fromInvite ? <p className="ds-cookie-description">{t('browserCookieImportHint')}</p> : null}
    {/* A fresh import has no history worth showing; progress and failures still are. */}
    {!fromInvite || busy || !['idle', 'cleared'].includes(current.status) ? <p role="status" className="ds-cookie-status">{t(`browserCookieStatus_${busy ? 'syncing' : current.status}`, { count: current.count, skipped: current.skipped, domains: current.domains ?? 0 })}</p> : null}
    {sources.length ? <label className="ds-cookie-source">
      <span>{t('browserCookieSource')}</span>
      <span className="ds-cookie-source-box">
        <span className="ds-chrome-logo" aria-hidden="true" />
        <span className="ds-cookie-source-browser">Google Chrome</span>
        {sources.length > 1 ? <>
          <select value={profile} disabled={busy} onChange={event => setProfile(event.target.value)}>
            <option value="">{t('browserCookieChooseSource')}</option>
            {sources.map(source => <option key={source.id} value={source.id}>{source.name}</option>)}
          </select>
          <ChevronDown size={16} aria-hidden="true" />
        </> : <span className="ds-cookie-source-profile">{sources[0].name}</span>}
      </span>
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
    {picking && profile && window.dsGui?.platform === 'darwin' ? <p className="ds-cookie-description">{t('browserCookieKeychainHint')}</p> : null}
    {!picking && selected.length ? <p className="ds-cookie-description">{t('browserCookieSelected', { count: selected.length, sites: selected.slice(0, 3).join(', ') + (selected.length > 3 ? '…' : '') })}</p> : null}
    {agentBusy && sources.length ? <p className="ds-cookie-description">{t('browserCookieAgentBusy')}</p> : null}
    <div className="ds-cookie-actions">
      {fromInvite ? <button type="button" className={button} disabled={busy} onClick={closePanel}>{t('browserCookieCancel')}</button>
        : current.consent === 'pending' ? <button type="button" className={button} disabled={busy}
          onClick={() => void perform('skip')}>{t(sources.length ? 'browserCookieSkip' : 'browserCookieContinue')}</button> : null}
      {changing ? <button type="button" className={button} disabled={busy} onClick={() => setChanging(false)}>{t('browserCookieKeepSites')}</button> : null}
      {sources.length && picking ? <button type="button" className="ds-cookie-primary" disabled={busy || agentBusy || current.status === 'syncing' || !profile || sites === null || (!chosen.size && !selected.length)}
        onClick={syncChosen}>
        {t(busy || current.status === 'syncing' ? 'browserCookieSyncing' : chosen.size ? 'browserCookieEnable' : 'browserCookieEnableEmpty', { count: chosen.size })}
      </button> : null}
      {sources.length && !picking ? <>
        <button type="button" className={button} disabled={busy} onClick={() => setChanging(true)}>{t('browserCookieChangeSites')}</button>
        <button type="button" className="ds-cookie-primary" disabled={busy || agentBusy || current.status === 'syncing'}
          onClick={() => void perform('sync')}>{t(busy || current.status === 'syncing' ? 'browserCookieSyncing' : 'browserCookieResync')}</button>
      </> : null}
    </div>
    {fromInvite ? null : <details className="ds-cookie-details">
      <summary>{t('browserCookieOptions')}</summary>
      <p>{t('browserCookieHint')}</p>
      {current.count > 0 || current.skipped > 0 ? <p>{t('browserCookieCounts', { count: current.count, domains: current.domains ?? 0, skipped: current.skipped })}</p> : null}
      <div className="ds-cookie-management">
      {manage && current.consent === 'enabled' ? <button type="button" className="ds-cookie-secondary" disabled={busy}
        onClick={() => void perform('disable')}>{t('browserCookieDisable')}</button> : null}
      {manage ? <button type="button" className="ds-cookie-danger" disabled={busy}
        onClick={() => void clearSignIns()}>{t('browserCookieClear')}</button> : null}
    </div>
    </details>}
    {error ? <p role="alert" className="mt-2 text-red-600">{t(error)}</p> : null}
    </div>
  </section>
  return modal ? modalSurface(content) : content
}
