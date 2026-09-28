import { useEffect, useMemo, useRef, useState } from 'react'
import { FolderOpen, Loader2, RefreshCw } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useChatStore } from '../../store/chat-store'
import { formatAutomationApiError } from '../../lib/automation-runtime-client'

type Source = 'codex' | 'claude'
type Session = {
  id: string; source: Source; path: string; title: string; workspace: string
  workspace_available: boolean; archived: boolean; model: string; message_count: number | null
  updated_at: string; warnings: string[]; imported_thread_id: string | null; history_only: boolean
}
type Scan = { root: string; available: boolean; sessions: Session[]; errors: { path: string; message: string }[] }
type Result = { status: 'imported' | 'skipped' | 'linked'; thread_id: string; history_only?: boolean; warnings: string[] }
const sources: Source[] = ['codex', 'claude']
const sourceName = (source: Source) => source === 'codex' ? 'Codex' : 'Claude Code'
const keyOf = (s: Session) => `${s.source}:${s.id}`
const groupOf = (s: Session) => `${s.source}:${s.workspace}`
const button = 'inline-flex items-center justify-center gap-2 rounded-lg border border-ds-border px-3 py-2 text-sm text-ds-ink hover:bg-ds-subtle disabled:cursor-not-allowed disabled:opacity-40'
const input = 'min-w-0 rounded-lg border border-ds-border bg-ds-elevated px-3 py-2 text-sm text-ds-ink'

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
  const [progress, setProgress] = useState({ done: 0, total: 0, title: '' })
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
  const eligible = (s: Session) => !s.imported_thread_id || (s.history_only && !!folders[groupOf(s)]?.trim())
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
          for (const issue of response.errors) issues.push(`${issue.path}: ${issue.message}`)
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
    setProgress({ done: 0, total: rows.length, title: '' })
    try {
      for (const [index, session] of rows.entries()) {
        if (stop.current) break
        const key = keyOf(session)
        setProgress({ done: index, total: rows.length, title: session.title })
        try {
          const result = await request<Result>('import', {
            source: session.source, root: scannedRoots[session.source], path: session.path,
            session_id: session.id, workspace: folders[groupOf(session)]?.trim() || null
          })
          if (!mounted.current) break
          setResults(current => ({ ...current, [key]: result }))
          setSessions(current => current.map(s => keyOf(s) === key ? {
            ...s, imported_thread_id: result.thread_id, warnings: result.warnings,
            history_only: result.status === 'linked' ? false : result.history_only ?? s.history_only
          } : s))
          setSelected(current => { const next = new Set(current); next.delete(key); return next })
        } catch (e) {
          if (!mounted.current) break
          setFailures(current => ({ ...current, [key]: e instanceof Error ? e.message : String(e) }))
        }
        if (mounted.current) setProgress({ done: index + 1, total: rows.length, title: session.title })
      }
    } finally {
      // A committed session remains available even when the user leaves this page.
      try { await refreshThreads() } catch (e) { if (mounted.current) setErrors(current => [...current, String(e)]) }
      if (mounted.current) { setRunning(false); setStopping(false) }
    }
  }

  const failedRows = sessions.filter(s => failures[keyOf(s)])
  return <div className="space-y-5 text-ds-ink">
    <section className="ds-content-card space-y-4 rounded-2xl p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-3">{sources.map(source => <label key={source} className={`${button} cursor-pointer`}>
          <input type="checkbox" checked={enabled[source]} disabled={busy} onChange={e => setEnabled({ ...enabled, [source]: e.target.checked })} />{sourceName(source)}
        </label>)}</div>
        <button className={button} disabled={busy || !sources.some(s => enabled[s])} onClick={() => void scan()}>
          {scanning ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          {t(scanning ? 'sessionImport.scanning' : scanned ? 'sessionImport.rescan' : 'sessionImport.scan')}
        </button>
      </div>
      <p className="text-sm leading-6 text-ds-muted">{t('sessionImport.description')}</p>
      <details className="text-sm text-ds-muted"><summary className="cursor-pointer">{t('sessionImport.customSource')}</summary>
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

    {scanned && <section className="ds-content-card overflow-hidden rounded-2xl">
      <div className="flex flex-wrap items-center gap-3 border-b border-ds-border p-4">
        <input className={`${input} flex-1`} type="search" aria-label={t('sessionImport.search')} placeholder={t('sessionImport.search')} value={query} disabled={busy} onChange={e => setQuery(e.target.value)} />
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={includeArchived} disabled={busy} onChange={e => setIncludeArchived(e.target.checked)} />{t('sessionImport.archived')}</label>
        <button className={button} disabled={busy} onClick={() => toggle(visible, true)}>{t('sessionImport.selectAll')}</button>
        <button className={button} disabled={busy} onClick={() => setSelected(new Set())}>{t('sessionImport.clear')}</button>
      </div>
      {!visible.length && <p className="p-6 text-center text-sm text-ds-muted">{t('sessionImport.empty')}</p>}
      <div className="max-h-[560px] divide-y divide-ds-border overflow-y-auto">{groups.map(([group, rows]) => {
        const first = rows[0]; const available = rows.filter(eligible)
        return <div key={group} className="p-4">
          <div className="flex items-start gap-3">
            <input type="checkbox" className="mt-1" aria-label={first.workspace || t('sessionImport.noProject')} checked={available.length > 0 && available.every(s => selected.has(keyOf(s)))} disabled={busy || !available.length} onChange={e => toggle(rows, e.target.checked)} />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap justify-between gap-2"><p className="font-medium">{first.workspace.split(/[\\/]/).filter(Boolean).pop() || t('sessionImport.noProject')}</p><span className="text-xs text-ds-muted">{sourceName(first.source)} · {t('sessionImport.conversations', { count: rows.length })}</span></div>
              <p className="mt-1 break-all text-xs text-ds-muted">{first.workspace || t('sessionImport.noProject')}</p>
              {!first.workspace_available && <p className="mt-2 text-sm text-amber-600 dark:text-amber-400">{t('sessionImport.missingFolder')}</p>}
              <details className="mt-3" open={!first.workspace_available || undefined}>
                <summary className="cursor-pointer text-xs text-ds-muted">{t('sessionImport.linkFolder')}</summary>
                <div className="mt-2 flex gap-2"><input className={`${input} flex-1`} aria-label={`${t('sessionImport.targetFolder')} ${first.workspace}`} placeholder={t('sessionImport.optionalFolder')} value={folders[group] ?? ''} disabled={busy} onChange={e => setFolders({ ...folders, [group]: e.target.value })} /><button className={button} disabled={busy} onClick={() => void pickFolder(group)}>{t('sessionImport.browse')}</button></div>
              </details>
              <details className="mt-3"><summary className="cursor-pointer text-sm text-ds-muted">{t('sessionImport.chooseSessions')}</summary>
                <div className="mt-2 space-y-3">{rows.map(session => <div key={keyOf(session)}>
                  <label className="flex items-start gap-2 text-sm"><input type="checkbox" className="mt-1" disabled={busy || !eligible(session)} checked={selected.has(keyOf(session)) && eligible(session)} onChange={e => toggle([session], e.target.checked)} />
                    <span className="min-w-0 flex-1"><span className="block break-words">{session.title}</span><span className="text-xs text-ds-muted">{new Date(session.updated_at).toLocaleString(i18n.language)} · {session.model} · {session.message_count !== null ? t('sessionImport.messages', { count: session.message_count }) : ''}{session.imported_thread_id ? ` · ${t(session.history_only ? 'sessionImport.historyOnly' : 'sessionImport.alreadyImported')}` : ''}</span></span>
                  </label>
                  {session.warnings.length > 0 && <p className="ml-6 mt-1 text-xs text-amber-600 dark:text-amber-400">{session.warnings.map(w => t(`sessionImport.warnings.${w}`)).join(' · ')}</p>}
                </div>)}</div>
              </details>
            </div>
          </div>
        </div>
      })}</div>
    </section>}

    <p className="text-xs leading-5 text-ds-muted">{t('sessionImport.limitations')}</p>
    {errors.length > 0 && <details className="rounded-xl border border-amber-300 p-3 text-sm"><summary className="cursor-pointer">{t('sessionImport.scanIssues', { count: errors.length })}</summary><div className="mt-2 max-h-40 overflow-auto">{errors.map((error, i) => <p key={i} className="break-all py-1">{error}</p>)}</div></details>}
    {(running || progress.total > 0) && <div role="status" aria-live="polite" className="rounded-xl bg-ds-subtle p-4 text-sm">
      <p>{t(running ? 'sessionImport.progress' : 'sessionImport.finished', { done: progress.done, total: progress.total })}</p>
      {running && <p className="mt-1 truncate text-ds-muted">{progress.title}</p>}
      <progress className="mt-2 w-full accent-accent" value={progress.done} max={progress.total} aria-label={t('sessionImport.progressLabel')} />
      <p className="mt-2 text-ds-muted">{t('sessionImport.result', { imported: Object.values(results).filter(r => r.status === 'imported').length, linked: Object.values(results).filter(r => r.status === 'linked').length, skipped: Object.values(results).filter(r => r.status === 'skipped').length, failed: Object.keys(failures).length })}</p>
    </div>}
    {failedRows.length > 0 && <div role="alert" className="max-h-48 space-y-2 overflow-auto rounded-xl border border-red-300 p-3 text-sm text-red-600">{failedRows.map(s => <p className="break-words" key={keyOf(s)}>{s.title}: {failures[keyOf(s)]}</p>)}</div>}
    <div className="flex flex-wrap justify-end gap-3">
      {running ? <button className={button} disabled={stopping} onClick={() => { stop.current = true; setStopping(true) }}>{t(stopping ? 'sessionImport.stopping' : 'sessionImport.stop')}</button> : <>
        {failedRows.length > 0 && <button className={button} disabled={busy} onClick={() => void run(failedRows)}>{t('sessionImport.retry')}</button>}
        <button className={`${button} bg-accent text-white hover:bg-accent/90`} disabled={busy || !chosen.length} onClick={() => void run(chosen)}>{t('sessionImport.importSelected', { count: chosen.length })}</button>
      </>}
    </div>
  </div>
}
