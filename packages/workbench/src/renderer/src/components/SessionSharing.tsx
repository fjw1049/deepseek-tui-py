import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Share, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useChatStore } from '../store/chat-store'
import { SharingError, sharingRequest, type SharePreview, type ShareSettings } from '../lib/session-sharing'
import { isChatsWorkspace, resolveActiveThreadWorkspace } from '../lib/workspace-path'

export function SessionSharing({ incomingUrl, onDismiss }: { incomingUrl?: string; onDismiss?: () => void }) {
  const { t } = useTranslation('common')
  const threadId = useChatStore(s => s.activeThreadId)
  const currentWorkspace = useChatStore(s => resolveActiveThreadWorkspace(s.activeThreadId, s.threads, s.workspaceRoot))
  const busy = useChatStore(s => s.busy)
  const refreshThreads = useChatStore(s => s.refreshThreads)
  const selectThread = useChatStore(s => s.selectThread)
  const [open, setOpen] = useState(!!incomingUrl)
  const [tab, setTab] = useState<'share' | 'restore'>(incomingUrl ? 'restore' : 'share')
  const [ready, setReady] = useState(false)
  const [includeProject, setIncludeProject] = useState(false)
  const [url, setUrl] = useState(incomingUrl ?? '')
  const [createdUrl, setCreatedUrl] = useState('')
  const [workspace, setWorkspace] = useState('')
  const targetWorkspace = workspace || (isChatsWorkspace(currentWorkspace) ? '' : currentWorkspace)
  const [restoreProject, setRestoreProject] = useState(true)
  const [preview, setPreview] = useState<SharePreview | null>(null)
  const [pending, setPending] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const dialog = useRef<HTMLDialogElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const field = 'w-full rounded-lg border border-ds-border bg-ds-elevated px-3 py-2 text-sm text-ds-ink'
  const button = 'rounded-lg border border-ds-border px-3 py-2 text-sm text-ds-ink hover:bg-ds-subtle disabled:opacity-40'
  const primary = `${button} bg-accent text-white hover:bg-accent/90`
  const errorMessage = useCallback((e: unknown): string => {
    if (e instanceof SharingError) {
      if ([404, 410].includes(e.status)) return t('sharing.linkUnavailable')
      if ([401, 403].includes(e.status)) return t('sharing.serviceUnavailable')
      if ([502, 503, 504].includes(e.status)) return t('sharing.connectionFailed')
      if (e.status === 409) return t('sharing.wait')
      if (e.message.includes('Not a valid object name')) return t('sharing.projectNeedsSync')
      if (e.message.includes('Invalid share link') || e.message.includes('service origin')) return t('sharing.invalidLink')
    }
    return e instanceof Error ? e.message : String(e)
  }, [t])

  useEffect(() => {
    if (!open) return
    dialog.current?.showModal()
    let live = true
    if (tab === 'share') {
      setPending(true)
      sharingRequest<ShareSettings>('settings', 'GET').then(config => {
        if (live) setReady(config.ready ?? !!(config.service_url && config.has_upload_key))
      }).catch(() => { if (live) setReady(false) }).finally(() => { if (live) setPending(false) })
    }
    return () => { live = false }
  }, [open, tab])
  useEffect(() => { setCreatedUrl('') }, [threadId, open, busy])
  useEffect(() => {
    if (!incomingUrl) return
    let live = true
    setPending(true)
    sharingRequest<SharePreview>('preview', 'POST', { url: incomingUrl })
      .then(value => { if (live) setPreview(value) })
      .catch(e => { if (live) setError(errorMessage(e)) })
      .finally(() => { if (live) setPending(false) })
    return () => { live = false }
  }, [incomingUrl, errorMessage])

  const close = () => {
    if (pending) return
    setOpen(false)
    onDismiss?.()
    trigger.current?.focus()
  }
  const run = async (action: () => Promise<void>) => {
    setPending(true); setError(''); setNotice('')
    try { await action() } catch (e) { setError(errorMessage(e)) }
    finally { setPending(false) }
  }
  const loadPreview = async () => {
    const value = await sharingRequest<SharePreview>('preview', 'POST', { url })
    setPreview(value)
  }

  return <>
    {!incomingUrl && <button ref={trigger} type="button" className="ds-sidebar-toggle-button ds-no-drag shrink-0"
      title={t('sharing.open')} aria-label={t('sharing.open')}
      onClick={() => { setTab(threadId ? 'share' : 'restore'); setWorkspace(''); setError(''); setNotice(''); setOpen(true) }}>
      <Share className="h-4 w-4" strokeWidth={1.85} />
    </button>}
    {open && createPortal(<dialog ref={dialog} aria-labelledby="session-sharing-title"
      onCancel={e => { e.preventDefault(); close() }}
      className="ds-no-drag m-auto max-h-[85vh] w-[480px] max-w-[calc(100vw-32px)] overflow-y-auto rounded-2xl border border-ds-border bg-ds-card p-5 text-ds-ink shadow-2xl backdrop:bg-black/40">
      <div className="mb-4 flex items-center justify-between">
        <h2 id="session-sharing-title" className="text-lg font-semibold">{t(tab === 'share' ? 'sharing.simpleTitle' : 'sharing.openLink')}</h2>
        <button className={button} disabled={pending} onClick={close} aria-label={t('sharing.close')}><X size={16} /></button>
      </div>
      {tab === 'share' ? <div className="space-y-4">
        <p className="text-sm text-ds-muted">{t('sharing.simpleHint')}</p>
        {!pending && !ready && <p role="status" className="rounded-lg bg-ds-subtle p-3 text-sm text-ds-muted">{t('sharing.unavailable')}</p>}
        {ready && <>
          <details className="text-sm text-ds-muted"><summary className="cursor-pointer">{t('sharing.moreOptions')}</summary>
            <label className="mt-3 flex gap-2"><input type="checkbox" checked={includeProject} disabled={pending || !!createdUrl} onChange={e => setIncludeProject(e.target.checked)} />{t('sharing.includeProject')}</label>
            <p className="mt-2 text-xs">{t('sharing.simpleProjectHint')}</p>
          </details>
          {busy && <p className="text-sm text-ds-muted">{t('sharing.wait')}</p>}
          <button className={primary} disabled={pending || busy || !threadId} onClick={() => void run(async () => {
            let link = createdUrl
            if (!link) {
              const result = await sharingRequest<{ url: string }>('shares', 'POST', { thread_id: threadId, include_project: includeProject, expires_in_days: 7 })
              link = result.url; setCreatedUrl(link)
            }
            try { await navigator.clipboard.writeText(link); setNotice(t('sharing.copiedSimple')) }
            catch { setNotice(t('sharing.copyManually')) }
          })}>{t('sharing.copy')}</button>
          {createdUrl && <>
            <input className={field} readOnly aria-label={t('sharing.link')} value={createdUrl} onFocus={e => e.target.select()} />
            <button className={button} disabled={pending} onClick={() => void run(async () => { await sharingRequest('revoke', 'POST', { url: createdUrl }); setCreatedUrl(''); setNotice(t('sharing.revoked')) })}>{t('sharing.revoke')}</button>
          </>}
        </>}
        <div className="border-t border-ds-border pt-3"><button className={button} disabled={pending} onClick={() => { setTab('restore'); setError(''); setNotice('') }}>{t('sharing.openLink')}</button></div>
      </div> : <div className="space-y-4">
        {!preview && <>
          <p className="text-sm text-ds-muted">{t('sharing.pasteHint')}</p>
          <input autoFocus className={field} aria-label={t('sharing.link')} placeholder={t('sharing.pastePlaceholder')} disabled={pending} value={url} onChange={e => { setUrl(e.target.value); setPreview(null) }} onKeyDown={e => { if (e.key === 'Enter' && !e.nativeEvent.isComposing && url && !pending) void run(loadPreview) }} />
          <button className={primary} disabled={pending || !url.trim()} onClick={() => void run(loadPreview)}>{t('sharing.openConversation')}</button>
        </>}
        {preview && <>
          <div className="rounded-lg border border-ds-border p-3">
            <p className="font-medium">{preview.title}</p>
            <p className="mt-1 text-xs text-ds-muted">{new Date(preview.created_at).toLocaleString()} · {t('sharing.turns', { count: preview.turn_count })}</p>
            <div className="mt-3 max-h-48 space-y-3 overflow-auto text-sm">{preview.messages.map((m, i) => <p key={i} className="whitespace-pre-wrap break-words"><b>{m.role === 'user_message' ? t('sharing.user') : 'AI'}: </b>{m.text}</p>)}</div>
          </div>
          {preview.project_commit ? <>
            <label className="flex gap-2 text-sm"><input type="checkbox" checked={restoreProject} disabled={pending} onChange={e => setRestoreProject(e.target.checked)} />{t('sharing.bringFiles')}</label>
            {restoreProject && <p className="text-xs text-ds-muted">{t('sharing.pickProjectHint')}</p>}
          </> : <p className="text-sm text-ds-muted">{t('sharing.continueHint')}</p>}
          <p className="text-sm text-ds-muted">{t('sharing.workspace')}: <span className="break-all">{targetWorkspace || t('sharing.temporaryWorkspace')}</span></p>
          <details className="text-sm text-ds-muted"><summary className="cursor-pointer">{t('sharing.useProject')}</summary>
            <button className={`${button} mt-2`} disabled={pending} onClick={() => void run(async () => { const picked = await window.dsGui.pickWorkspaceDirectory(); if (picked.path) setWorkspace(picked.path) })}>{t('sharing.choose')}</button>
          </details>
          {busy && <p className="text-sm text-ds-muted">{t('sharing.waitRestore')}</p>}
          <button className={primary} disabled={pending || busy} onClick={() => void run(async () => {
            let target = targetWorkspace
            if (preview.project_commit && restoreProject && !target) {
              const picked = await window.dsGui.pickWorkspaceDirectory()
              if (!picked.path) return
              target = picked.path; setWorkspace(target)
            }
            const thread = await sharingRequest<{ id: string }>('restore', 'POST', { url, ...(target ? { workspace: target } : {}), restore_project: restoreProject })
            await refreshThreads(); await selectThread(thread.id); setOpen(false); onDismiss?.()
          })}>{t('sharing.continueSimple')}</button>
          <button className={`${button} ml-2`} disabled={pending} onClick={() => { setPreview(null); setWorkspace('') }}>{t('sharing.changeLink')}</button>
        </>}
      </div>}
      {pending && <p role="status" className="mt-3 text-sm text-ds-muted">{t('sharing.working')}</p>}
      {notice && <p role="status" className="mt-3 text-sm">{notice}</p>}
      {error && <p role="alert" className="mt-3 whitespace-pre-wrap text-sm text-red-500">{error}</p>}
    </dialog>, document.body)}
  </>
}

export function SharedLinkReceiver() {
  const [url, setUrl] = useState<string | null>(null)
  useEffect(() => {
    const api = window.dsGui
    if (!api.getSharedLink || !api.onSharedLinkAvailable) return
    let live = true
    const take = () => { void api.getSharedLink!().then(link => { if (live && link) setUrl(link) }).catch(() => {}) }
    const off = api.onSharedLinkAvailable(take)
    take()
    return () => { live = false; off() }
  }, [])
  return url ? <SessionSharing key={url} incomingUrl={url} onDismiss={() => {
    void window.dsGui.clearSharedLink?.(url).catch(() => {})
    setUrl(null)
  }} /> : null
}
