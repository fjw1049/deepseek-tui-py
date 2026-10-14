import { useCallback, useEffect, useId, useMemo, useRef, useState, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { ArrowLeft, ArrowRight, ChevronDown, RotateCw, Globe2, Plus, X, MoreHorizontal, Camera, Hand, Play, Video, Film, Square, MousePointer2, Copy, ExternalLink, Bug, FileCode2, LoaderCircle } from 'lucide-react'
import type { ChatBlock } from '../agent/types'
import { extractDetectedDevPreviewUrls, formatDevPreviewUrlLabel } from '../lib/dev-preview-detection'
import { parsePreviewPickConsoleMessage, PREVIEW_PICK_CONSOLE_PREFIX, type PreviewElementPick } from '../lib/preview-element-picker'
import { isHtmlPreviewPath } from '@shared/html-preview'
import { BrowserCookieSync, type CookieSyncState } from './BrowserCookieSync'
import { DevBrowserPanel } from './DevBrowserPanel'
import { BrowserViewport } from './BrowserViewport'
import { formatAutomationApiError } from '../lib/automation-runtime-client'
import { normalizeBrowseUrlInput } from '@shared/dev-preview-url'
import { useLightDismiss } from '../hooks/use-light-dismiss'
import './browser-workspace.css'
import { respondToAssistance } from './BrowserAssistance'
import type { Assistance } from './BrowserAssistanceCard'

type BrowserState = {
  cookie_sync?: CookieSyncState
  assistance?: Assistance | null
  active: boolean; url?: string; generation?: number; transferring?: boolean
  task_paused?: boolean; task_running?: boolean; task_pausing?: boolean
  viewport?: { width: number; height: number }
  tabs?: { tab_id: string; title: string; url: string; active: boolean }[]
  image?: string | null; video_recording?: boolean; video_error?: string | null
  owner: 'agent' | 'user' | 'stopped'; recording: boolean
  activity?: string; workflow_recording?: boolean
  error: string | null; log: { action: string; success: boolean }[]
  artifacts: { id: string; label: string; path: string }[]
  scene?: { scene_id: string; tab_id: string; document_id: string; viewport_epoch: number }
  view_sequence?: number
  frame_status?: 'ready' | 'busy' | 'changed'
  capabilities?: { video?: { ready: boolean } }
  unresolved?: ActionReceipt[]
  dialog?: { id: string; type: string; message: string } | null
  file_chooser?: { id: string; mode: string } | null
  downloads?: { id: string; state: string; filename: string; received_bytes: number; path?: string }[]
}

type ActionReceipt = { action?: string; target_url?: string; action_id: string; execution: string; effect?: string; reconciliation?: unknown }
type ActionResult = { success?: boolean; content?: unknown; receipt?: ActionReceipt; dialog?: BrowserState['dialog'] }
export class BrowserRequestError extends Error {
  constructor(message: string, readonly result?: ActionResult) { super(message) }
}

export async function browserRequest<T>(threadId: string, suffix = '', body?: unknown): Promise<T> {
  const response = await window.dsGui.runtimeRequest(`/v1/threads/${encodeURIComponent(threadId)}/browser${suffix}`,
    body === undefined ? 'GET' : 'POST', body === undefined ? undefined : JSON.stringify(body))
  if (!response.ok) {
    let result: ActionResult | undefined
    try {
      const data = JSON.parse(response.body); const detail = data.detail ?? data
      if (detail && typeof detail === 'object' && detail.receipt) result = detail
    } catch { /* The runtime may also return a plain transport error. */ }
    throw new BrowserRequestError(formatAutomationApiError(response.body, `HTTP ${response.status}`), result)
  }
  return JSON.parse(response.body) as T
}

type BrowserWorkspaceProps = {
  agentRequest?: number
  threadId: string | null; visible?: boolean; blocks?: ChatBlock[]; className?: string
  preferredUrl?: string | null; preferredFilePath?: string | null; externalError?: string | null
  onPreferredUrlConsumed?: () => void; onExternalErrorConsumed?: () => void
  onPreviewPick?: (pick: PreviewElementPick) => void
  onOpenFileInEditor?: (path: string) => void
}

export function BrowserWorkspace({ agentRequest = 0, ...props }: BrowserWorkspaceProps): ReactElement {
  const { t } = useTranslation('common')
  const [mode, setMode] = useState<'preview' | 'agent'>(agentRequest ? 'agent' : 'preview')
  const [agentOpened, setAgentOpened] = useState(!!agentRequest)
  useEffect(() => {
    if (props.preferredUrl || props.externalError) setMode('preview')
  }, [props.preferredUrl, props.externalError])
  useEffect(() => {
    if (agentRequest) { setMode('agent'); setAgentOpened(true) }
  }, [agentRequest])
  return <div className="flex h-full min-h-0 flex-col">
    <div className={mode === 'preview' ? 'min-h-0 flex-1' : 'hidden'} inert={mode !== 'preview'}>
      <DevBrowserPanel {...props} blocks={props.blocks ?? []} className="h-full w-full"
        visible={props.visible !== false && mode === 'preview'} />
    </div>
    {agentOpened ? <div className={mode === 'agent' ? 'min-h-0 flex-1' : 'hidden'} inert={mode !== 'agent'}>
      {props.threadId ? <AgentBrowserPanel key={props.threadId} {...props} threadId={props.threadId}
        visible={props.visible !== false && mode === 'agent'} preferredUrl={null} externalError={null}
        onReturnToPages={() => setMode('preview')} /> :
        <p className="p-5 text-sm text-ds-muted">{t('browserNeedThread')}</p>}
    </div> : null}
  </div>
}

export function AgentBrowserPanel({ threadId, visible = true, blocks = [], preferredUrl, preferredFilePath,
  onPreferredUrlConsumed, externalError, onExternalErrorConsumed, onPreviewPick, onOpenFileInEditor,
  onReturnToPages }: BrowserWorkspaceProps & {
    threadId: string; onReturnToPages?: () => void
  }): ReactElement {
  const [dialogAnswer, setDialogAnswer] = useState('')
  const { t } = useTranslation('common')
  const [state, setState] = useState<BrowserState | null>(null)
  useEffect(() => { setDialogAnswer('') }, [state?.dialog?.id])
  const [image, setImage] = useState<string | null>(null)
  const [frameFresh, setFrameFresh] = useState(false)
  const [url, setUrl] = useState('')
  const [error, setError] = useState('')
  const [connectionError, setConnectionError] = useState('')
  const [pending, setPending] = useState(false)
  const [controlTarget, setControlTarget] = useState<'agent' | 'user' | 'stopped' | null>(null)
  const [more, setMore] = useState(false)
  const controlOptionsId = useId()
  const [controlOpen, setControlOpen] = useState(false)
  const controlRoot = useRef<HTMLElement>(null)
  const controlButton = useRef<HTMLButtonElement>(null)
  const [controlPosition, setControlPosition] = useState({ x: 0.5, y: 0 })
  const controlDrag = useRef<{ id: number; x: number; y: number; left: number; top: number } | null>(null)
  const suppressControlClick = useRef(false)
  useLightDismiss({ open: controlOpen, refs: [controlRoot], onDismiss: () => {
    if (controlRoot.current?.contains(document.activeElement)) controlButton.current?.focus()
    setControlOpen(false)
  } })
  const [cookieSettings, setCookieSettings] = useState(false)
  const [cookieAnchor, setCookieAnchor] = useState<DOMRect | null>(null)
  const menuRoot = useRef<HTMLDivElement>(null)
  const menuButton = useRef<HTMLButtonElement>(null)
  const [fresh, setFresh] = useState(false)
  useLightDismiss({ open: more, refs: [menuRoot], onDismiss: () => setMore(false) })
  useEffect(() => { if (!visible) { setMore(false); setControlOpen(false); setCookieSettings(false); setFresh(false); setFrameFresh(false) } }, [visible])
  useEffect(() => {
    if (more) menuRoot.current?.querySelector<HTMLButtonElement>('[role="menuitem"]:not(:disabled)')?.focus()
  }, [more])
  const alive = useRef(true)
  const transferring = useRef(false)
  const latestGeneration = useRef(-1)
  const latestView = useRef(-1)
  const [lastReceipt, setLastReceipt] = useState<ActionReceipt | null>(null)
  const lastPreferred = useRef<string | null>(null)
  const [previewFiles, setPreviewFiles] = useState<Record<string, string>>({})
  const [waitingPreview, setWaitingPreview] = useState<{ url: string; filePath?: string | null } | null>(null)
  const [inspect, setInspect] = useState(false)
  const [notice, setNotice] = useState('')
  useEffect(() => {
    if (!notice) return
    const timer = window.setTimeout(() => setNotice(''), 4000)
    return () => window.clearTimeout(timer)
  }, [notice])
  const detectedUrls = useMemo(() => extractDetectedDevPreviewUrls(blocks), [blocks])
  const filePath = state?.url ? previewFiles[state.url.split('#')[0]] : undefined
  const canInspect = !!filePath && isHtmlPreviewPath(filePath) && !!onPreviewPick
  useEffect(() => { setInspect(false) }, [visible, state?.url, state?.generation, state?.owner])
  useEffect(() => { if (externalError) { setError(externalError); onExternalErrorConsumed?.() } }, [externalError, onExternalErrorConsumed])
  const userControls = visible && fresh && state?.owner === 'user' && !state.transferring && !pending
  const canNavigate = visible && fresh && !pending && !state?.transferring && (!state?.active || userControls)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  useEffect(() => { if (state?.url) setUrl(state.url === 'about:blank' ? '' : state.url) }, [state?.url])
  const displayedScene = useRef<string | undefined>(undefined)
  const apply = useCallback((next: BrowserState): void => {
    if (!alive.current || transferring.current || (next.generation ?? -1) < latestGeneration.current) return
    if ((next.generation ?? -1) > latestGeneration.current) latestView.current = -1
    if (next.view_sequence !== undefined && next.view_sequence < latestView.current) return
    if (next.view_sequence !== undefined) latestView.current = next.view_sequence
    const sameGeneration = (next.generation ?? -1) === latestGeneration.current
    latestGeneration.current = next.generation ?? -1
    const sameScene = next.scene?.scene_id === displayedScene.current
    if (next.image) displayedScene.current = next.scene?.scene_id
    setFresh(true)
    setFrameFresh(previous => !next.transferring && !!next.active && (
      !!next.image || (previous && sameGeneration && sameScene && next.frame_status === 'busy')
    ))
    setState(next); if (next.image) setImage(next.image); else if (!next.active) setImage(null)
  }, [])
  useEffect(() => {
    if (!visible) return
    let disposed = false
    let timer: ReturnType<typeof setTimeout>
    const poll = async (): Promise<void> => {
      let delay = 600
      const started = performance.now()
      try {
        const next = await browserRequest<BrowserState>(threadId, '/view')
        if (!disposed) {
          apply(next); setConnectionError('')
          delay = next.active ? (next.owner === 'user' ? Math.max(16, 50 - (performance.now() - started)) : 300) : 600
        }
      } catch (e) { if (!disposed) { setFresh(false); setFrameFresh(false); setConnectionError(e instanceof Error ? e.message : String(e)) } }
      finally { if (!disposed) timer = setTimeout(() => void poll(), delay) }
    }
    void poll(); return () => { disposed = true; clearTimeout(timer) }
  }, [threadId, visible, apply])
  const perform = useCallback(async (suffix: string, body: unknown): Promise<boolean> => {
    setError(''); setPending(true)
    try {
      const payload = suffix === '/action' && state?.active ? { ...(body as Record<string, unknown>), generation: state.generation } : body
      const result = await browserRequest<ActionResult>(threadId, suffix, payload)
      if (!alive.current) return false
      if (result.receipt) setLastReceipt(result.receipt)
      if (result.dialog) setState(previous => previous ? { ...previous, dialog: result.dialog } : previous)
      if (result.success === false) setError(typeof result.content === 'string' ? result.content : JSON.stringify(result.content))
      try { apply(await browserRequest<BrowserState>(threadId, '/view')); setConnectionError('') }
      catch (e) {
        if (alive.current) {
          setFresh(false); setFrameFresh(false)
          setConnectionError(e instanceof Error ? e.message : String(e))
          if (result.receipt?.execution === 'executed') setNotice(t('browserActionSentViewUnavailable'))
        }
      }
      return result.success !== false
    } catch (e) {
      if (alive.current) {
        if (e instanceof BrowserRequestError && e.result?.receipt) setLastReceipt(e.result.receipt)
        setError(e instanceof Error ? e.message : String(e))
      }
      return false
    }
    finally { if (alive.current) setPending(false) }
  }, [threadId, apply, state?.active, state?.generation, t])
  const action = useCallback((body: unknown): void => { void perform('/action', body) }, [perform])
  async function refreshBrowser(): Promise<void> {
    setPending(true); setFrameFresh(false)
    try {
      if (state?.active) await browserRequest(threadId, '/action', { action: 'observe', generation: state.generation })
      apply(await browserRequest<BrowserState>(threadId, '/view'))
      setLastReceipt(null); setError(''); setConnectionError('')
    } catch (e) { setConnectionError(e instanceof Error ? e.message : String(e)) }
    finally { setPending(false) }
  }
  async function control(owner: 'agent' | 'user' | 'stopped'): Promise<void> {
    setPending(true); setControlTarget(owner); setError(''); transferring.current = true
    try {
      if (state?.assistance && owner !== 'stopped') {
        await respondToAssistance(threadId, state.assistance.id, owner === 'user' ? 'takeover' : 'continue')
        transferring.current = false
        apply(await browserRequest<BrowserState>(threadId, '/view'))
        return
      }
      const next = await browserRequest<BrowserState>(threadId, '/control', { owner, generation: state?.generation })
      transferring.current = false
      if (!alive.current) return
      apply(next)
      if (owner === 'user' && next.unresolved?.length) {
        await browserRequest(threadId, '/action', { action: 'observe', generation: next.generation })
        apply(await browserRequest<BrowserState>(threadId, '/view'))
        setLastReceipt(null)
        setControlOpen(true)
      }
      if (owner === 'stopped') onReturnToPages?.()

    } catch (e) { if (alive.current) setError(e instanceof Error ? e.message : String(e)) }
    finally { transferring.current = false; if (alive.current) { setPending(false); setControlTarget(null) } }
  }
  const openPreview = useCallback(async (target: string, source?: string | null): Promise<void> => {
    const normalized = normalizeBrowseUrlInput(target)
    if (!normalized) { setError(t('browserInvalidUrl')); return }
    if (state?.active && !userControls) { setWaitingPreview({ url: normalized, filePath: source }); return }
    const existing = state?.tabs?.find(tab => tab.url === normalized)
    const opened = await perform('/action', existing ? { action: 'switch_tab', tab_id: existing.tab_id } :
      { action: state?.active ? 'new_tab' : 'open', url: normalized })
    if (opened && source) setPreviewFiles(current => ({ ...current, [normalized.split('#')[0]]: source }))
    if (opened) setWaitingPreview(null)
  }, [state, userControls, perform, t])
  useEffect(() => {
    if (!preferredUrl) { lastPreferred.current = null; return }
    if (!visible || !fresh || pending || lastPreferred.current === preferredUrl) return
    lastPreferred.current = preferredUrl
    void openPreview(preferredUrl, preferredFilePath)
    onPreferredUrlConsumed?.()
  }, [visible, fresh, preferredUrl, preferredFilePath, pending, openPreview, onPreferredUrlConsumed])
  async function openDevTools(): Promise<void> {
    try {
      const result = await browserRequest<{ url: string }>(threadId, '/input', { kind: 'devtools', generation: state?.generation ?? 0 })
      await window.dsGui.openExternal(result.url)
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
  }
  async function copyScreenshot(): Promise<void> {
    try {
      const snapshot = await browserRequest<BrowserState>(threadId, '/view')
      if (!snapshot.image) throw new Error(t('browserScreenshotFailed'))
      const img = new Image(); img.src = snapshot.image; await img.decode()
      const canvas = document.createElement('canvas'); canvas.width = img.naturalWidth; canvas.height = img.naturalHeight
      canvas.getContext('2d')!.drawImage(img, 0, 0)
      const blob = await new Promise<Blob>((resolve, reject) => canvas.toBlob(value => value ? resolve(value) : reject(new Error(t('browserScreenshotFailed'))), 'image/png'))
      await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })])
      setNotice(t('browserScreenshotCopied'))
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
  }
  function navigate(): void {
    const value = url.trim(); if (!value) return
    const isSearch = /\s/.test(value) || (!/[.:/]/.test(value) && !/^\d+$/.test(value) && value !== 'localhost')
    const target = isSearch ? `https://www.google.com/search?q=${encodeURIComponent(value)}` : normalizeBrowseUrlInput(value)
    if (!target) { setError(t('browserInvalidUrl')); return }
    action({ action: 'open', url: target })
  }
  const controlBusy = controlTarget !== null || !!state?.transferring || !!state?.task_pausing
  const unresolvedReceipt = state?.unresolved?.[0] || (lastReceipt?.execution === 'unknown' && !lastReceipt.reconciliation ? lastReceipt : null)
  const reviewActionLabel = ({ click: 'browserClick', fill: 'browserFill', open: 'browserOpen', reload: 'browserReload' } as Record<string, string>)[unresolvedReceipt?.action ?? '']
  const requiresReview = !!(unresolvedReceipt || state?.dialog || state?.file_chooser)
  const hasConnectionProblem = !!(error || connectionError || state?.error)
  const needsAttention = !!(unresolvedReceipt || state?.dialog || state?.file_chooser || waitingPreview || error || connectionError || state?.error)
  const needsHelp = state?.assistance?.status === 'pending'
  const controlTone = needsHelp || needsAttention ? 'attention' : state?.owner === 'user' ? 'human' : state?.active && state.task_running ? 'agent' : 'idle'
  const controlTitle = controlTarget === 'user' ? 'browserPausing' : controlTarget === 'agent' ? 'browserResuming'
    : controlTarget === 'stopped' ? 'browserWorking' : state?.task_pausing ? 'browserTaskPausing'
    : state?.transferring ? 'browserWorking' : requiresReview || needsHelp ? 'browserWaitingForYou' : hasConnectionProblem ? 'browserConnectionProblem' : !state?.active ? 'browserIdle'
    : state.owner === 'user' ? state.task_paused ? 'browserTaskPaused' : 'browserUserControl' : state.task_paused ? 'browserControlPaused'
    : state.task_running === false ? 'browserAgentReady' : 'browserAgentControl'
  const controlHint = controlBusy ? 'browserControlSwitchHint' : unresolvedReceipt ? 'browserReviewHint' : requiresReview ? 'browserResponseHint' : hasConnectionProblem ? 'browserReconnectHint' : needsHelp ? 'browserControlHelpHint'
    : state?.owner === 'user' ? state.task_running || state.task_paused ? 'browserControlHumanHint' : 'browserControlHumanIdleHint'
    : state?.active && state.task_running ? 'browserAgentHint' : 'browserControlReadyHint'
  return <div className={`ds-shared-browser${state?.assistance?.status === 'human' ? ' is-human-assistance' : ''}`}>
    {visible ? <BrowserCookieSync threadId={threadId} state={state?.cookie_sync} generation={state?.generation}
      manage={cookieSettings} anchor={cookieAnchor} onOpen={anchor => { setCookieAnchor(anchor ?? null); setCookieSettings(true) }} onClose={() => { setCookieSettings(false); menuButton.current?.focus() }} /> : null}
    <div className="ds-dev-browser__chrome ds-browser-chrome">
      <div className="ds-dev-browser__tabs">
        <div className="ds-dev-browser__tab-scroll" aria-label={t('browserTabs')}>
          {(state?.tabs?.length ? state.tabs : [{ tab_id: '', title: t('browserNewTab'), url: '', active: true }]).map(tab =>
            <div className={`ds-dev-browser__tab${tab.active ? ' ds-dev-browser__tab--active' : ''}`} key={tab.tab_id}>
              <button className="ds-dev-browser__tab-main" aria-pressed={tab.active} disabled={!canNavigate} title={tab.title || tab.url}
                onClick={() => { if (tab.tab_id) action({ action: 'switch_tab', tab_id: tab.tab_id }) }}>
                <Globe2 className="ds-dev-browser__tab-icon" /><span className="ds-dev-browser__tab-label">{tab.url === 'about:blank' ? t('browserNewTab') : tab.title || t('browserNewTab')}</span>
              </button>
              {tab.tab_id ? <button className={`ds-dev-browser__tab-close${tab.active ? ' is-visible' : ''}`} aria-label={`${t('browserCloseTab')} ${tab.title}`} title={t('browserCloseTab')} disabled={!canNavigate}
                onClick={() => action({ action: 'close_tab', tab_id: tab.tab_id })}><X size={11} /></button> : null}
            </div>)}
        </div>
        <button className="ds-dev-browser__icon-btn" aria-label={t('browserNewTab')} title={t('browserNewTab')} disabled={!canNavigate} onClick={() => action({ action: 'new_tab' })}><Plus size={14} /></button>
      </div>
      <form className="ds-dev-browser__toolbar" onSubmit={(e) => { e.preventDefault(); navigate() }}>
        <div className="ds-dev-browser__nav">
          <button type="button" className="ds-dev-browser__icon-btn" aria-label={t('browserBack')} title={t('browserBack')} disabled={!userControls} onClick={() => action({ action: 'back' })}><ArrowLeft size={14} /></button>
          <button type="button" className="ds-dev-browser__icon-btn" aria-label={t('browserForward')} title={t('browserForward')} disabled={!userControls} onClick={() => action({ action: 'forward' })}><ArrowRight size={14} /></button>
          <button type="button" className="ds-dev-browser__icon-btn" aria-label={t('browserReload')} title={t('browserReload')} disabled={!userControls} onClick={() => action({ action: 'reload' })}><RotateCw size={13} /></button>
        </div>
        <input className="ds-dev-browser__omnibox" aria-label={t('browserAddressPlaceholder')} placeholder={t('browserAddressPlaceholder')} value={url} disabled={!canNavigate} onChange={(e) => setUrl(e.target.value)} />
        <button className="ds-dev-browser__icon-btn" aria-label={t('browserOpen')} title={t('browserOpen')} disabled={!canNavigate || !url.trim()}><ArrowRight size={13} /></button>
        {canInspect ? <button type="button" className="ds-dev-browser__icon-btn" aria-label={t('browserInspect')} title={t('browserInspectHint')} aria-pressed={inspect} disabled={!userControls} onClick={() => setInspect(!inspect)}><MousePointer2 size={15} /></button> : null}
        <div className="ds-browser-menu-anchor" ref={menuRoot}>
          <button ref={menuButton} type="button" className="ds-dev-browser__icon-btn" aria-label={t('browserMore')} title={t('browserMore')} aria-haspopup="menu" aria-expanded={more} onClick={() => setMore(!more)}><MoreHorizontal size={16} /></button>
          {more ? <div className="ds-dock-menu" role="menu" aria-label={t('browserMore')}
            onClick={(e) => { if ((e.target as Element).closest('button')) setMore(false) }}
            onKeyDown={(e) => {
              if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); setMore(false); menuButton.current?.focus() }
              else if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key)) {
                e.preventDefault()
                const items = [...e.currentTarget.querySelectorAll<HTMLButtonElement>('[role="menuitem"]:not(:disabled)')]
                const index = items.indexOf(document.activeElement as HTMLButtonElement)
                const next = e.key === 'Home' ? 0 : e.key === 'End' ? items.length - 1 : (index + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length
                items[next]?.focus()
              } else if (e.key === 'Tab') setMore(false)
            }}>
            <button type="button" role="menuitem" className="ds-dock-menu-item" aria-haspopup="dialog" onClick={event => { setCookieAnchor(menuButton.current?.getBoundingClientRect() ?? event.currentTarget.getBoundingClientRect()); setCookieSettings(true) }}><Globe2 size={15} />{t('browserCookieManage')}</button>
            <button type="button" role="menuitem" className="ds-dock-menu-item" disabled={!userControls} onClick={() => action({ action: 'screenshot' })}><Camera size={15} />{t('browserSaveEvidence')}</button>
            <button type="button" role="menuitem" className="ds-dock-menu-item" disabled={!userControls || state?.capabilities?.video?.ready === false} title={state?.capabilities?.video?.ready === false ? t('browserVideoUnavailable') : undefined} onClick={() => action({ action: state?.video_recording ? 'video_stop' : 'video_start' })}><Video size={15} />{t(state?.video_recording ? 'browserVideoStop' : 'browserVideoStart')}</button>
            <button type="button" role="menuitem" className="ds-dock-menu-item" disabled={!userControls} onClick={() => action({ action: state?.recording ? 'record_stop' : 'record_start' })}><Film size={15} />{t(state?.recording ? 'browserFinishRecording' : 'browserRecordSteps')}</button>
            <div className="ds-browser-menu-divider" role="separator" />
            {filePath && isHtmlPreviewPath(filePath) && onOpenFileInEditor ? <button type="button" role="menuitem" className="ds-dock-menu-item" onClick={() => onOpenFileInEditor(filePath)}><FileCode2 size={15} />{t('browserEditSource')}</button> : null}
            <button type="button" role="menuitem" className="ds-dock-menu-item" disabled={!userControls} onClick={() => void openDevTools()}><Bug size={15} />{t('browserDevTools')}</button>
            <button type="button" role="menuitem" className="ds-dock-menu-item" disabled={!image} onClick={() => void copyScreenshot()}><Copy size={15} />{t('browserCopyScreenshot')}</button>
            <button type="button" role="menuitem" className="ds-dock-menu-item" disabled={!state?.url || !normalizeBrowseUrlInput(state.url)} onClick={() => { if (state?.url) void window.dsGui.openExternal(state.url).catch(e => setError(String(e))) }}><ExternalLink size={15} />{t('browserOpenExternal')}</button>
            <div className="ds-browser-menu-divider" role="separator" />
            <button type="button" role="menuitem" className="ds-dock-menu-item" disabled={!state?.active || pending} onClick={() => void control('stopped')}><Square size={15} />{t(state?.task_running ? 'browserEndTaskAndSession' : 'browserEndSession')}</button>
          </div> : null}
        </div>
      </form>
      {detectedUrls.length ? <div className="ds-dev-browser__chips">{detectedUrls.map(target => <button key={target} className="ds-dev-browser__chip" disabled={pending || !fresh} title={target} onClick={() => void openPreview(target)}>{formatDevPreviewUrlLabel(target)}</button>)}</div> : null}
    </div>
    <div className="ds-browser-content">
    {inspect || notice ? <div className="ds-browser-feedback" role="status"><span>{inspect ? t('browserPickInstruction') : notice}</span><button aria-label={t('browserDismissPreview')} onClick={() => { setInspect(false); setNotice('') }}><X size={13} /></button></div> : null}

    <header ref={controlRoot} className={`ds-browser-status is-${controlTone}`} style={{
      left: `calc(${controlPosition.x * 100}% + ${8 - controlPosition.x * 16}px)`,
      top: `calc(${controlPosition.y * 100}% + ${8 - controlPosition.y * 16}px)`,
      transform: `translate(${-controlPosition.x * 100}%, ${-controlPosition.y * 100}%)`
    }} aria-label={t('browserControlLabel')}
      onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setControlOpen(false) }}>
      <button ref={controlButton} type="button" className="ds-browser-status-trigger" aria-expanded={controlOpen}
        aria-controls={controlOptionsId}
        onPointerDown={event => {
          if (event.button !== 0 || !event.isPrimary) return
          const rect = controlRoot.current!.getBoundingClientRect()
          controlDrag.current = { id: event.pointerId, x: event.clientX, y: event.clientY, left: rect.left, top: rect.top }
          suppressControlClick.current = false
          event.currentTarget.setPointerCapture(event.pointerId)
        }}
        onPointerMove={event => {
          const drag = controlDrag.current
          if (!drag || drag.id !== event.pointerId) return
          const dx = event.clientX - drag.x, dy = event.clientY - drag.y
          if (!suppressControlClick.current && Math.hypot(dx, dy) < 5) return
          suppressControlClick.current = true
          const panel = controlRoot.current!
          const bounds = panel.parentElement!.getBoundingClientRect()
          const rect = panel.getBoundingClientRect()
          setControlPosition({
            x: Math.max(0, Math.min(1, (drag.left + dx - bounds.left - 8) / Math.max(1, bounds.width - rect.width - 16))),
            y: Math.max(0, Math.min(1, (drag.top + dy - bounds.top - 8) / Math.max(1, bounds.height - rect.height - 16)))
          })
        }}
        onPointerUp={event => {
          if (controlDrag.current?.id !== event.pointerId) return
          controlDrag.current = null
          event.currentTarget.releasePointerCapture(event.pointerId)
        }}
        onPointerCancel={() => { controlDrag.current = null; suppressControlClick.current = true }}
        onLostPointerCapture={() => { controlDrag.current = null }}
        onClick={event => {
          if (event.detail !== 0 && suppressControlClick.current) { suppressControlClick.current = false; return }
          setControlOpen(!controlOpen)
        }}>
        <span className="ds-browser-status-copy" role="status" aria-live="polite" aria-atomic="true">
          <strong><span className="ds-browser-status-dot" aria-hidden="true" />{t(controlTitle)}{needsAttention && !requiresReview && !hasConnectionProblem ? <span className="ds-browser-attention">{t('browserNeedsAttention')}</span> : state?.downloads?.length ? <span className="ds-browser-attention">{t('browserDownloads')}</span> : null}</strong>
        </span>
        <ChevronDown size={14} aria-hidden="true" className={controlOpen ? 'is-open' : ''} />
      </button>
      {controlOpen ? <div id={controlOptionsId} className="ds-browser-control-details">
        <p>{t(controlHint)}</p>
        {state?.active && !(requiresReview && state.owner === 'user') && (!hasConnectionProblem || requiresReview) ? <button type="button" className="ds-browser-control" disabled={!visible || !fresh || pending || controlBusy}
          aria-busy={controlBusy} onClick={() => {
            setControlOpen(false); controlButton.current?.focus()
            void control(state.owner === 'user' ? 'agent' : 'user')
          }}>
          {controlBusy ? <LoaderCircle className="ds-browser-control-spinner" size={14} /> : state.owner === 'user' ? <Play size={14} /> : <Hand size={14} />}
          {t(controlBusy ? 'browserControlSwitching' : requiresReview && state.owner !== 'user' ? 'browserInspectAndHandle' : state.assistance && state.owner === 'user' ? 'browserAssistContinue' : state.owner === 'user' ? state.task_running === false ? 'browserGiveControl' : 'browserReturnControl' : 'browserTakeControl')}
        </button> : null}
    {waitingPreview ? <div className="ds-browser-notice"><span>{t('browserPreviewWaiting')}</span><button disabled={!userControls} onClick={() => void openPreview(waitingPreview.url, waitingPreview.filePath)}>{t('browserOpen')}</button><button aria-label={t('browserDismissPreview')} onClick={() => setWaitingPreview(null)}><X size={13} /></button></div> : null}
    {unresolvedReceipt && userControls ?
      <div role="status" className="ds-browser-notice"><span>{t('browserOutcomeUnknown')}</span>
        <button disabled={pending} onClick={() => void refreshBrowser()}>{t('browserRefreshView')}</button>
        {reviewActionLabel ? <strong>{t('browserReviewAction', { action: t(reviewActionLabel) })}</strong> : null}
        {unresolvedReceipt.target_url ? <span className="ds-browser-review-url">{unresolvedReceipt.target_url}</span> : null}
        {['executed', 'not_executed'].map(outcome => <button key={outcome} disabled={!userControls} onClick={() => {
          const receipt = unresolvedReceipt
          if (receipt) void action({ action: 'resolve_operation', operation_id: receipt.action_id, outcome,
            reason: t(outcome === 'executed' ? 'browserReviewedDone' : 'browserReviewedNotDone') })
        }}>{t(outcome === 'executed' ? 'browserReviewedDone' : 'browserReviewedNotDone')}</button>)}
      <button onClick={() => { setControlOpen(false); controlButton.current?.focus() }}>{t('browserReviewLater')}</button>
      </div> : null}
    {state?.dialog && userControls ? <div role="dialog" aria-label={t('browserNativeDialog')} className="ds-browser-notice">
      <span>{state.dialog.message}</span>
      {state.dialog.type === 'prompt' ? <input aria-label={t('browserDialogAnswer')} value={dialogAnswer} onChange={e => setDialogAnswer(e.target.value)} /> : null}
      <button disabled={pending || state.owner !== 'user'} onClick={() => void action({ action: 'handle_dialog', dialog_id: state.dialog?.id, accept: true, text: dialogAnswer })}>{t('browserDialogAccept')}</button>
      <button disabled={pending || state.owner !== 'user'} onClick={() => void action({ action: 'handle_dialog', dialog_id: state.dialog?.id, accept: false })}>{t('browserDialogDismiss')}</button>
    </div> : null}
    {state?.file_chooser && userControls ? <div className="ds-browser-notice"><span>{t('browserChooseFiles')}</span>
      <button disabled={pending || state.owner !== 'user'} onClick={() => void (async () => {
        const chooser = state.file_chooser
        const picked = await window.dsGui.pickWorkspaceFiles()
        if (picked.ok && chooser) await action({ action: 'upload', chooser_id: chooser.id, files: picked.paths })
      })().catch(e => setError(String(e)))}>{t('browserChooseFiles')}</button>
      <button disabled={pending || state.owner !== 'user'} onClick={() => void action({ action: 'upload', chooser_id: state.file_chooser?.id, files: [] })}>{t('browserDialogDismiss')}</button>
    </div> : null}
    {state?.downloads?.length ? <div className="ds-browser-notice">{state.downloads.map(item =>
      <span key={item.id}>{item.filename} · {item.state === 'completed' ? t('browserDownloadReady') : t('browserDownloadPending')}
        {item.state === 'completed' && item.path ? <button onClick={() => void window.dsGui.showItemInFolder(item.path!)}>{t('browserDownloadReady')}</button> : null}
      </span>)}</div> : null}
    {hasConnectionProblem && !requiresReview ? <div className="ds-browser-notice">
      <button disabled={pending || controlBusy} onClick={() => void refreshBrowser()}>{t('browserRefreshView')}</button>
      <details><summary>{t('browserTechnicalDetails')}</summary><pre>{error || connectionError || state?.error}</pre></details>
    </div> : null}
      </div> : null}
    </header>
      {image && state?.active ? <BrowserViewport image={image} enabled={!!userControls && frameFresh && !controlOpen && !more && !state.dialog} reviewOnly={!!unresolvedReceipt} resizeEnabled={!!userControls && frameFresh && !controlOpen && !more && !state.video_recording} generation={state.generation ?? 0}
        sceneId={state.scene?.scene_id} inspect={inspect && canInspect} onInspectCancel={() => setInspect(false)} width={state.viewport?.width ?? 1200} height={state.viewport?.height ?? 760} label={t('browserLiveView')}
        send={async (body) => {
          if (body.kind === 'pick') {
            const result = await browserRequest<{ pick?: unknown; url?: string }>(threadId, '/input', body)
            const parsed = parsePreviewPickConsoleMessage(PREVIEW_PICK_CONSOLE_PREFIX + JSON.stringify({ type: 'pick', payload: result.pick }))
            if (alive.current && parsed?.type === 'pick' && filePath && result.url?.split('#')[0] === state.url?.split('#')[0]) {
              onPreviewPick?.({ ...parsed.payload, filePath }); setInspect(false); setNotice(t('browserPickAdded'))
            }
            return {}
          }
          if (body.kind !== 'resize') {
            try {
              const result = await browserRequest<ActionResult & { text?: string }>(threadId, '/input', body)
              if (result.receipt && alive.current) setLastReceipt(result.receipt)
              return result
            } catch (e) {
              if (alive.current && e instanceof Error && /Browser (page|control) changed; queued input was discarded/.test(e.message)) {
                setFrameFresh(false)
                try {
                  apply(await browserRequest<BrowserState>(threadId, '/view'))
                  setError(''); setConnectionError('')
                  setNotice(t('browserInputDiscarded'))
                } catch (refreshError) {
                  setConnectionError(refreshError instanceof Error ? refreshError.message : String(refreshError))
                }
                return { discardQueued: true }
              }
              if (alive.current && e instanceof BrowserRequestError && e.result?.receipt) setLastReceipt(e.result.receipt)
              throw e
            }
          }
          setPending(true)
          try {
            const result = await browserRequest<{ text?: string }>(threadId, '/input', body)
            try { apply(await browserRequest<BrowserState>(threadId, '/view')) }
            catch (e) { if (alive.current) { setFresh(false); setFrameFresh(false); setConnectionError(e instanceof Error ? e.message : String(e)) } }
            return result
          } finally { if (alive.current) setPending(false) }
        }} onError={setError} /> :
        <div className="ds-browser-empty"><Globe2 size={28} strokeWidth={1.3} /><h3>{t(pending ? 'browserStarting' : 'browserStartTitle')}</h3><p>{t('browserStartHint')}</p></div>}

    </div>
  </div>
}
