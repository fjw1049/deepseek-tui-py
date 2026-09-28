import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowDownToLine, Check, CheckCircle2, ChevronRight, Folder, FolderOpen, History, Info, Loader2, RefreshCw, Search } from 'lucide-react'
import codexIcon from '../../assets/provider-icons/openai.svg'
import claudeIcon from '../../assets/provider-icons/claude.svg'
import './session-import.css'
import { useTranslation } from 'react-i18next'
import { useChatStore } from '../../store/chat-store'
import { formatAutomationApiError } from '../../lib/automation-runtime-client'

type Source = 'codex' | 'claude'
type Session = {
  id: string; source: Source; path: string; title: string; workspace: string
  workspace_available: boolean; archived: boolean; model: string; message_count: number | null
  updated_at: string; warnings: string[]; imported_thread_id: string | null; history_only: boolean; update_available?: boolean
}
type Scan = { root: string; available: boolean; sessions: Session[]; errors: { path: string; message: string }[] }
type Result = { status: 'imported' | 'updated' | 'skipped' | 'linked'; thread_id: string; history_only?: boolean; warnings: string[] }
const sources: Source[] = ['codex', 'claude']
const sourceName = (source: Source) => source === 'codex' ? 'Codex' : 'Claude Code'
const keyOf = (s: Session) => `${s.source}:${s.id}`
const groupOf = (s: Session) => `${s.source}:${s.workspace}`
const button = 'session-import-button'
const input = 'session-import-input'

function SourceBadge({ source }: { source: Source }) {
  return <span className={`session-import-source-badge ${source}`}>
    <img src={source === 'codex' ? codexIcon : claudeIcon} alt="" />{sourceName(source)}
  </span>
}

async function request<T>(path: string, payload: unknown): Promise<T> {
  const result = await window.dsGui.runtimeRequest(`/v1/external-sessions/${path}`, 'POST', JSON.stringify(payload))
  if (!result.ok) throw new Error(formatAutomationApiError(result.body, `HTTP ${result.status}`))
  return JSON.parse(result.body) as T
}

export function SessionImportPanel() {
  const { t, i18n } = useTranslation('settings')
  const refreshThreads = useChatStore(s => s.refreshThreads)
  const [enabled, setEnabled] = useState<Record<Source, boolean>>({ codex: true, claude: true })
  const [roots, setRoots] = useState<Record<Source, string>>({ codex: '', claude: '' })
  const [scannedRoots, setScannedRoots] = useState<Record<Source, string>>({ codex: '', claude: '' })
  const [sessions, setSessions] = useState<Session[]>([])
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [folders, setFolders] = useState<Record<string, string>>({})
  const [query, setQuery] = useState('')
  const [includeArchived, setIncludeArchived] = useState(false)
  const [scanning, setScanning] = useState(false)
  const [scanned, setScanned] = useState(false)
  const [running, setRunning] = useState(false)
  const [stopping, setStopping] = useState(false)
  const [errors, setErrors] = useState<string[]>([])
  const [results, setResults] = useState<Record<string, Result>>({})
  const [failures, setFailures] = useState<Record<string, string>>({})
  const [progress, setProgress] = useState<{ done: number; total: number; title: string; source: Source | null }>({ done: 0, total: 0, title: '', source: null })
  const stop = useRef(false)
  const mounted = useRef(true)
  const busy = scanning || running
  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false; stop.current = true }
  }, [])

  const visible = useMemo(() => sessions.filter(s => enabled[s.source] && (includeArchived || !s.archived)
    && `${s.workspace} ${s.title}`.toLowerCase().includes(query.trim().toLowerCase())), [sessions, enabled, includeArchived, query])
  const groups = useMemo(() => {
    const map = new Map<string, Session[]>()
    for (const session of visible) {
      const key = groupOf(session)
      map.set(key, [...(map.get(key) ?? []), session])
    }
    return [...map.entries()]
  }, [visible])
  const eligible = (s: Session) => !s.imported_thread_id || !!s.update_available || (s.history_only && !!folders[groupOf(s)]?.trim())
  const chosen = visible.filter(s => selected.has(keyOf(s)) && eligible(s))
  const toggle = (rows: Session[], checked: boolean) => setSelected(current => {
    const next = new Set(current)
    for (const row of rows.filter(eligible)) { if (checked) next.add(keyOf(row)); else next.delete(keyOf(row)) }
    return next
  })

  async function scan() {
    setScanning(true); setErrors([]); setResults({}); setFailures({}); setSelected(new Set())
    const found: Session[] = []; const issues: string[] = []; const nextRoots = { ...scannedRoots }
    try {
      for (const source of sources.filter(s => enabled[s])) {
        try {
          const response = await request<Scan>('scan', { source, root: roots[source].trim() || null })
          found.push(...response.sessions); nextRoots[source] = response.root
          if (!response.available) issues.push(t('sessionImport.notFound', { source: sourceName(source), path: response.root }))
          for (const issue of response.errors) issues.push(`${sourceName(source)} · ${issue.path}: ${issue.message}`)
        } catch (e) { issues.push(`${sourceName(source)}: ${e instanceof Error ? e.message : String(e)}`) }
        if (!mounted.current) return
      }
      setSessions(found); setScannedRoots(nextRoots); setErrors(issues); setScanned(true)
    } finally { if (mounted.current) setScanning(false) }
  }

  async function pickFolder(group: string) {
    try {
      const picked = await window.dsGui.pickWorkspaceDirectory(folders[group] || undefined)
      if (picked.path && mounted.current) setFolders(current => ({ ...current, [group]: picked.path! }))
    } catch (e) { setErrors(current => [...current, String(e)]) }
  }

  async function run(rows: Session[]) {
    if (!rows.length || busy) return
    stop.current = false; setStopping(false); setRunning(true); setFailures({}); setResults({})
    setProgress({ done: 0, total: rows.length, title: '', source: null })
    try {
      for (const [index, session] of rows.entries()) {
        if (stop.current) break
        const key = keyOf(session)
        setProgress({ done: index, total: rows.length, title: session.title, source: session.source })
        try {
          const result = await request<Result>('import', {
            source: session.source, root: scannedRoots[session.source], path: session.path,
            session_id: session.id, workspace: folders[groupOf(session)]?.trim() || null
          })
          if (!mounted.current) break
          setResults(current => ({ ...current, [key]: result }))
          setSessions(current => current.map(s => keyOf(s) === key ? {
            ...s, imported_thread_id: result.thread_id, warnings: result.warnings,
            update_available: result.status === 'linked' ? s.update_available : false,
            history_only: result.status === 'linked' ? false : result.history_only ?? s.history_only
          } : s))
          setSelected(current => { const next = new Set(current); next.delete(key); return next })
        } catch (e) {
          if (!mounted.current) break
          setFailures(current => ({ ...current, [key]: e instanceof Error ? e.message : String(e) }))
        }
        if (mounted.current) setProgress({ done: index + 1, total: rows.length, title: session.title, source: session.source })
      }
    } finally {
      // A committed session remains available even when the user leaves this page.
      try { await refreshThreads() } catch (e) { if (mounted.current) setErrors(current => [...current, String(e)]) }
      if (mounted.current) { setRunning(false); setStopping(false) }
    }
  }

  const failedRows = sessions.filter(s => failures[keyOf(s)])
  return <div className="session-import space-y-5 text-ds-ink">
    <section className="session-import-sources">
      <div className="session-import-section-heading">
        <div className="session-import-step"><span>01</span><h2>{t('sessionImport.chooseSource')}</h2></div>
        <span className="session-import-local"><History size={13} aria-hidden="true" />{t('sessionImport.localCopy')}</span>
      </div>
      <p className="session-import-description">{t('sessionImport.description')}</p>
      <div className="session-import-source-grid">{sources.map(source => <label key={source} className={`session-import-source ${enabled[source] ? 'is-selected' : ''} ${busy ? 'is-disabled' : ''}`}>
        <input className="sr-only" type="checkbox" checked={enabled[source]} disabled={busy} onChange={e => setEnabled({ ...enabled, [source]: e.target.checked })} />
        <span className={`session-import-brand ${source}`}><img src={source === 'codex' ? codexIcon : claudeIcon} alt="" /></span>
        <span className="min-w-0 flex-1"><span className="session-import-source-name">{sourceName(source)}</span><span className="session-import-source-path">{roots[source] || (source === 'codex' ? '~/.codex' : '~/.claude')}</span></span>
        <span className="session-import-source-check" aria-hidden="true">{enabled[source] && <Check size={13} strokeWidth={2.5} />}</span>
      </label>)}</div>
      <div className="session-import-scan-row">
        <span className="text-xs text-ds-muted">{t('sessionImport.scanHint')}</span>
        <button className={`${button} session-import-scan`} disabled={busy || !sources.some(s => enabled[s])} onClick={() => void scan()}>
          {scanning ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          {t(scanning ? 'sessionImport.scanning' : scanned ? 'sessionImport.rescan' : 'sessionImport.scan')}
        </button>
      </div>
      <details className="session-import-advanced text-sm text-ds-muted"><summary><ChevronRight size={14} aria-hidden="true" />{t('sessionImport.customSource')}</summary>
        <div className="mt-3 space-y-3">{sources.map(source => <label key={source} className="block">
          <span>{sourceName(source)}</span><div className="mt-1 flex gap-2">
            <input className={`${input} flex-1`} aria-label={`${sourceName(source)} ${t('sessionImport.sourceFolder')}`} placeholder={source === 'codex' ? '~/.codex' : '~/.claude'} value={roots[source]} disabled={busy} onChange={e => setRoots({ ...roots, [source]: e.target.value })} />
            <button className={button} disabled={busy} aria-label={`${sourceName(source)} ${t('sessionImport.browse')}`} onClick={() => {
              void window.dsGui.pickWorkspaceDirectory(roots[source] || undefined).then(p => { if (p.path && mounted.current) setRoots(current => ({ ...current, [source]: p.path! })) }).catch(e => setErrors(current => [...current, String(e)]))
            }}><FolderOpen className="h-4 w-4" /></button>
          </div>
        </label>)}</div>
        <p className="mt-2 text-xs">{t('sessionImport.sourceHint')}</p>
      </details>
    </section>

    {scanned && <section className="session-import-projects">
      <div className="session-import-section-heading px-5 pt-5">
        <div className="session-import-step"><span>02</span><h2>{t('sessionImport.chooseProjects')}</h2></div>
        <span className="session-import-count">{t('sessionImport.found', { projects: groups.length, count: visible.length })}</span>
      </div>
      <div className="session-import-filter">
        <div className="session-import-search"><Search size={16} aria-hidden="true" /><input className={input} type="search" aria-label={t('sessionImport.search')} placeholder={t('sessionImport.search')} value={query} disabled={busy} onChange={e => setQuery(e.target.value)} /></div>
        <label className="session-import-archive"><input type="checkbox" checked={includeArchived} disabled={busy} onChange={e => setIncludeArchived(e.target.checked)} />{t('sessionImport.archived')}</label>
        <button className={`${button} session-import-quiet`} disabled={busy} onClick={() => toggle(visible, true)}>{t('sessionImport.selectAll')}</button>
        <button className={`${button} session-import-quiet`} disabled={busy} onClick={() => setSelected(new Set())}>{t('sessionImport.clear')}</button>
      </div>
      {!visible.length && <div className="session-import-empty"><Search size={26} strokeWidth={1.5} aria-hidden="true" /><p>{t('sessionImport.empty')}</p></div>}
      <div className="session-import-project-list">{groups.map(([group, rows]) => {
        const first = rows[0]; const available = rows.filter(eligible)
        const pickedCount = available.filter(s => selected.has(keyOf(s))).length
        const allImported = rows.every(s => s.imported_thread_id && !s.history_only && !s.update_available)
        return <div key={group} className={`session-import-project ${pickedCount ? 'has-selection' : ''}`}>
          <div className="flex items-start gap-3">
            <input type="checkbox" className="mt-1" aria-label={first.workspace || t('sessionImport.noProject')} checked={available.length > 0 && available.every(s => selected.has(keyOf(s)))} disabled={busy || !available.length} onChange={e => toggle(rows, e.target.checked)} />
            <span className="session-import-folder"><Folder size={19} strokeWidth={1.7} aria-hidden="true" /></span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center justify-between gap-2"><p className="text-[14px] font-semibold tracking-tight">{first.workspace.split(/[\\/]/).filter(Boolean).pop() || t('sessionImport.noProject')}</p><span className="session-import-project-meta">{allImported && <span className="session-import-done"><CheckCircle2 size={12} />{t('sessionImport.alreadyImported')}</span>}<SourceBadge source={first.source} /><span>{t('sessionImport.conversations', { count: rows.length })}</span></span></div>
              <p className="session-import-path">{first.workspace || t('sessionImport.noProject')}</p>
              {!first.workspace_available && <p className="session-import-folder-notice"><Info size={14} aria-hidden="true" /><span>{t('sessionImport.missingFolder')}</span></p>}
              <details className="session-import-disclosure mt-3" open={!first.workspace_available || undefined}>
                <summary><ChevronRight size={13} aria-hidden="true" />{t('sessionImport.linkFolder')}</summary>
                <div className="mt-2 flex gap-2"><input className={`${input} flex-1`} aria-label={`${t('sessionImport.targetFolder')} ${first.workspace}`} placeholder={t('sessionImport.optionalFolder')} value={folders[group] ?? ''} disabled={busy} onChange={e => setFolders({ ...folders, [group]: e.target.value })} /><button className={button} disabled={busy} onClick={() => void pickFolder(group)}>{t('sessionImport.browse')}</button></div>
              </details>
              <details className="session-import-disclosure session-import-conversations mt-3"><summary><ChevronRight size={13} aria-hidden="true" />{t('sessionImport.chooseSessions')}</summary>
                <div className="session-import-session-list">{rows.map(session => <div className="session-import-session" key={keyOf(session)}>
                  <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1" disabled={busy || !eligible(session)} checked={selected.has(keyOf(session)) && eligible(session)} onChange={e => toggle([session], e.target.checked)} />
                    <span className="min-w-0 flex-1"><span className="flex flex-wrap items-center gap-2"><SourceBadge source={session.source} /><span className="min-w-0 break-words">{session.title}</span></span><span className="text-xs text-ds-muted">{new Date(session.updated_at).toLocaleString(i18n.language)} · {session.model} · {session.message_count !== null ? t('sessionImport.messages', { count: session.message_count }) : ''}{session.imported_thread_id ? ` · ${t(session.update_available ? 'sessionImport.updateAvailable' : session.history_only ? 'sessionImport.historyOnly' : 'sessionImport.alreadyImported')}` : ''}</span></span>
                  </label>
                  {session.warnings.length > 0 && <p className="ml-6 mt-1 text-xs text-amber-600 dark:text-amber-400">{session.warnings.map(w => t(`sessionImport.warnings.${w}`)).join(' · ')}</p>}
                </div>)}</div>
              </details>
            </div>
          </div>
        </div>
      })}</div>
    </section>}

    {!scanned && <div className="session-import-empty session-import-welcome"><span className="session-import-empty-icon"><ArrowDownToLine size={26} strokeWidth={1.5} aria-hidden="true" /></span><h3>{t('sessionImport.readyTitle')}</h3><p>{t('sessionImport.readyBody')}</p></div>}
    <details className="session-import-advanced session-import-notes"><summary><Info size={14} aria-hidden="true" />{t('sessionImport.notesTitle')}<ChevronRight size={13} aria-hidden="true" /></summary><p className="mt-3 text-xs leading-6 text-ds-muted">{t('sessionImport.limitations')}</p></details>
    {errors.length > 0 && <details className="rounded-xl border border-amber-300 p-3 text-sm"><summary className="cursor-pointer">{t('sessionImport.scanIssues', { count: errors.length })}</summary><div className="mt-2 max-h-40 overflow-auto">{errors.map((error, i) => <p key={i} className="break-all py-1">{error}</p>)}</div></details>}
    {(running || progress.total > 0) && <div role="status" aria-live="polite" className="session-import-progress">
      <div className="session-import-progress-heading">{running ? <Loader2 size={18} className="animate-spin" /> : <CheckCircle2 size={18} />}<p>{t(running ? 'sessionImport.progress' : 'sessionImport.finished', { done: progress.done, total: progress.total })}</p><span>{Math.round(progress.done / progress.total * 100)}%</span></div>
      {running && <div className="mt-2 flex min-w-0 items-center gap-2">{progress.source && <SourceBadge source={progress.source} />}<p className="min-w-0 truncate text-ds-muted">{progress.title}</p></div>}
      <progress className="mt-2 w-full accent-accent" value={progress.done} max={progress.total} aria-label={t('sessionImport.progressLabel')} />
      <p className="mt-2 text-ds-muted">{t('sessionImport.result', { updated: Object.values(results).filter(r => r.status === 'updated').length, imported: Object.values(results).filter(r => r.status === 'imported').length, linked: Object.values(results).filter(r => r.status === 'linked').length, skipped: Object.values(results).filter(r => r.status === 'skipped').length, failed: Object.keys(failures).length })}</p>
    </div>}
    {failedRows.length > 0 && <div role="alert" className="max-h-48 space-y-2 overflow-auto rounded-xl border border-red-300 p-3 text-sm text-red-600">{failedRows.map(s => <p className="break-words" key={keyOf(s)}><SourceBadge source={s.source} /> <span>{s.title}: {failures[keyOf(s)]}</span></p>)}</div>}
    <div className="session-import-footer">
      <div className="session-import-selection"><span className="session-import-selection-icon"><ArrowDownToLine size={18} aria-hidden="true" /></span><div><p>{t('sessionImport.selection', { count: chosen.length })}</p><span>{t('sessionImport.selectionHint')}</span></div></div>
      <div className="flex flex-wrap gap-2">{running ? <button className={button} disabled={stopping} onClick={() => { stop.current = true; setStopping(true) }}>{t(stopping ? 'sessionImport.stopping' : 'sessionImport.stop')}</button> : <>
        {failedRows.length > 0 && <button className={button} disabled={busy} onClick={() => void run(failedRows)}>{t('sessionImport.retry')}</button>}
        <button className={`${button} session-import-primary`} disabled={busy || !chosen.length} onClick={() => void run(chosen)}><ArrowDownToLine size={15} aria-hidden="true" />{t('sessionImport.importSelected', { count: chosen.length })}</button>
      </>}</div>
    </div>
  </div>
}
