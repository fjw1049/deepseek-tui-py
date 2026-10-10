import { useCallback, useEffect, useMemo, useRef, useState, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { ArrowLeft, ArrowRight, RotateCw, Globe2, Plus, X, MoreHorizontal, Camera, Bot, Hand, Play, Settings2, Video, Film, Square, MousePointer2, Copy, ExternalLink, Bug, FileCode2, LoaderCircle } from 'lucide-react'
import type { ChatBlock } from '../agent/types'
import { extractDetectedDevPreviewUrls, formatDevPreviewUrlLabel } from '../lib/dev-preview-detection'
import { parsePreviewPickConsoleMessage, PREVIEW_PICK_CONSOLE_PREFIX, type PreviewElementPick } from '../lib/preview-element-picker'
import { isHtmlPreviewPath } from '@shared/html-preview'
import { BrowserSessionSettings } from './BrowserSessionSettings'
import { DevBrowserPanel } from './DevBrowserPanel'
import { BrowserViewport } from './BrowserViewport'
import { formatAutomationApiError } from '../lib/automation-runtime-client'
import { normalizeBrowseUrlInput } from '@shared/dev-preview-url'
import { useLightDismiss } from '../hooks/use-light-dismiss'
import './browser-workspace.css'
import { respondToAssistance } from './BrowserAssistance'
import type { Assistance } from './BrowserAssistanceCard'

type BrowserState = {
  assistance?: Assistance | null
  active: boolean; url?: string; generation?: number; transferring?: boolean
  task_paused?: boolean; task_running?: boolean; task_pausing?: boolean
  viewport?: { width: number; height: number }
  tabs?: { tab_id: string; title: string; url: string; active: boolean }[]
  image?: string | null; video_recording?: boolean; video_error?: string | null
  owner: 'agent' | 'user' | 'stopped'; recording: boolean; demo_status: string
  activity?: string; workflow_recording?: boolean; demo_step?: number; demo_total?: number
  error: string | null; log: { action: string; success: boolean }[]
  artifacts: { id: string; label: string; path: string }[]
}

export async function browserRequest<T>(threadId: string, suffix = '', body?: unknown): Promise<T> {
  const response = await window.dsGui.runtimeRequest(`/v1/threads/${encodeURIComponent(threadId)}/browser${suffix}`,
    body === undefined ? 'GET' : 'POST', body === undefined ? undefined : JSON.stringify(body))
  if (!response.ok) throw new Error(formatAutomationApiError(response.body, `HTTP ${response.status}`))
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
  const [detailsRequest, setDetailsRequest] = useState(0)
  useEffect(() => {
    if (props.preferredUrl || props.externalError) setMode('preview')
  }, [props.preferredUrl, props.externalError])
  useEffect(() => {
    if (agentRequest) { setMode('agent'); setAgentOpened(true) }
  }, [agentRequest])
  return <div className="flex h-full min-h-0 flex-col">
    <div className={mode === 'preview' ? 'min-h-0 flex-1' : 'hidden'} inert={mode !== 'preview'}>
      <DevBrowserPanel {...props} blocks={props.blocks ?? []} className="h-full w-full"
        visible={props.visible !== false && mode === 'preview'}
        onOpenAutomation={props.threadId ? () => {
          setDetailsRequest(value => value + 1); setAgentOpened(true); setMode('agent')
        } : undefined} />
    </div>
    {agentOpened ? <div className={mode === 'agent' ? 'min-h-0 flex-1' : 'hidden'} inert={mode !== 'agent'}>
      {props.threadId ? <AgentBrowserPanel key={props.threadId} {...props} threadId={props.threadId}
        visible={props.visible !== false && mode === 'agent'} preferredUrl={null} externalError={null}
        detailsRequest={detailsRequest} onReturnToPages={() => setMode('preview')} /> :
        <p className="p-5 text-sm text-ds-muted">{t('browserNeedThread')}</p>}
    </div> : null}
  </div>
}

export function AgentBrowserPanel({ threadId, visible = true, blocks = [], preferredUrl, preferredFilePath,
  onPreferredUrlConsumed, externalError, onExternalErrorConsumed, onPreviewPick, onOpenFileInEditor,
  detailsRequest = 0, onReturnToPages }: BrowserWorkspaceProps & {
    threadId: string; detailsRequest?: number; onReturnToPages?: () => void
  }): ReactElement {
  const { t } = useTranslation('common')
  const [state, setState] = useState<BrowserState | null>(null)
  const [image, setImage] = useState<string | null>(null)
  const [artifactImage, setArtifactImage] = useState<string | null>(null)
  const [url, setUrl] = useState('')
  const [selector, setSelector] = useState('')
  const [text, setText] = useState('')
  const [dom, setDom] = useState('')
  const [error, setError] = useState('')
  const [connectionError, setConnectionError] = useState('')
  const [pending, setPending] = useState(false)
  const [controlTarget, setControlTarget] = useState<'agent' | 'user' | 'stopped' | null>(null)
  const [more, setMore] = useState(false)
  const [details, setDetails] = useState(!!detailsRequest)
  useEffect(() => { if (detailsRequest) setDetails(true) }, [detailsRequest])
  const menuRoot = useRef<HTMLDivElement>(null)
  const menuButton = useRef<HTMLButtonElement>(null)
  const detailsButton = useRef<HTMLButtonElement>(null)
  const [fresh, setFresh] = useState(false)
  useLightDismiss({ open: more, refs: [menuRoot], onDismiss: () => setMore(false) })
  useEffect(() => { if (!visible) { setMore(false); setDetails(false); setFresh(false) } }, [visible])
  useEffect(() => {
    if (more) menuRoot.current?.querySelector<HTMLButtonElement>('[role="menuitem"]:not(:disabled)')?.focus()
  }, [more])
  useEffect(() => { if (details) detailsButton.current?.focus() }, [details])
  const alive = useRef(true)
  const transferring = useRef(false)
  const latestGeneration = useRef(-1)
  const lastPreferred = useRef<string | null>(null)
  const [previewFiles, setPreviewFiles] = useState<Record<string, string>>({})
  const [waitingPreview, setWaitingPreview] = useState<{ url: string; filePath?: string | null } | null>(null)
  const [inspect, setInspect] = useState(false)
  const [notice, setNotice] = useState('')
  const detectedUrls = useMemo(() => extractDetectedDevPreviewUrls(blocks), [blocks])
  const filePath = state?.url ? previewFiles[state.url.split('#')[0]] : undefined
  const canInspect = !!filePath && isHtmlPreviewPath(filePath) && !!onPreviewPick
  useEffect(() => { setInspect(false) }, [visible, state?.url, state?.generation, state?.owner])
  useEffect(() => { if (externalError) { setError(externalError); onExternalErrorConsumed?.() } }, [externalError, onExternalErrorConsumed])
  const userControls = visible && fresh && state?.owner === 'user' && !state.transferring && !pending
  const canNavigate = visible && fresh && !pending && !state?.transferring && (!state?.active || userControls)
  const button = 'inline-flex items-center gap-1 rounded-md border border-ds-border px-2 py-1.5 text-xs disabled:opacity-40'
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  useEffect(() => { if (state?.url) setUrl(state.url === 'about:blank' ? '' : state.url) }, [state?.url])
  const apply = useCallback((next: BrowserState): void => {
    if (!alive.current || transferring.current || (next.generation ?? -1) < latestGeneration.current && next.active) return
    latestGeneration.current = next.generation ?? -1
    setState(next); if (next.image) setImage(next.image); else if (!next.active) setImage(null)
  }, [])
  useEffect(() => {
    if (!visible) return
    let disposed = false
    let timer: ReturnType<typeof setTimeout>
    const poll = async (): Promise<void> => {
      let delay = 600
      try {
        const next = await browserRequest<BrowserState>(threadId, '/view')
        if (!disposed) {
          apply(next); setConnectionError(''); setFresh(true)
          delay = next.active ? (next.owner === 'user' ? 120 : 300) : 600
        }
      } catch (e) { if (!disposed) setConnectionError(e instanceof Error ? e.message : String(e)) }
      finally { if (!disposed) timer = setTimeout(() => void poll(), delay) }
    }
    void poll(); return () => { disposed = true; clearTimeout(timer) }
  }, [threadId, visible, apply])
  const perform = useCallback(async (suffix: string, body: unknown): Promise<boolean> => {
    setError(''); setPending(true)
    try {
      const result = await browserRequest<{ success?: boolean; content?: unknown }>(threadId, suffix, body)
      if (result.success === false) throw new Error(typeof result.content === 'string' ? result.content : JSON.stringify(result.content))
      if (!alive.current) return false
      if (result.content !== undefined) setDom(typeof result.content === 'string' ? result.content : JSON.stringify(result.content))
      apply(await browserRequest<BrowserState>(threadId, '/view'))
      return true
    } catch (e) { if (alive.current) setError(e instanceof Error ? e.message : String(e)); return false }
    finally { if (alive.current) setPending(false) }
  }, [threadId, apply])
  const action = useCallback((body: unknown): void => { void perform('/action', body) }, [perform])
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
  const needsHelp = state?.assistance?.status === 'pending'
  const controlTone = needsHelp ? 'attention' : state?.owner === 'user' ? 'human' : state?.active && state.task_running ? 'agent' : 'idle'
  const controlTitle = controlTarget === 'user' ? 'browserPausing' : controlTarget === 'agent' ? 'browserResuming'
    : controlTarget === 'stopped' ? 'browserWorking' : state?.task_pausing ? 'browserTaskPausing'
    : state?.transferring ? 'browserWorking' : !state?.active ? 'browserIdle' : needsHelp ? 'browserControlNeedsHelp'
    : state.owner === 'user' ? state.task_paused ? 'browserTaskPaused' : 'browserUserControl' : state.task_paused ? 'browserControlPaused'
    : state.task_running === false ? 'browserAgentReady' : 'browserAgentControl'
  const controlHint = controlBusy ? 'browserControlSwitchHint' : needsHelp ? 'browserControlHelpHint'
    : state?.owner === 'user' ? state.task_running || state.task_paused ? 'browserControlHumanHint' : 'browserControlHumanIdleHint'
    : state?.active && state.task_running ? 'browserAgentHint' : 'browserControlReadyHint'
  return <div className={`ds-shared-browser${state?.assistance?.status === 'human' ? ' is-human-assistance' : ''}`}>
    <header className={`ds-browser-status is-${controlTone}`} aria-label={t('browserControlLabel')}>
      <span className="ds-browser-status-icon" aria-hidden="true">
        {controlBusy ? <LoaderCircle className="ds-browser-control-spinner" size={18} /> : state?.owner === 'user' || needsHelp ? <Hand size={18} /> : <Bot size={18} />}
      </span>
      <div className="ds-browser-status-copy" role="status" aria-live="polite" aria-atomic="true">
        <strong><span className="ds-browser-status-dot" aria-hidden="true" />{t(controlTitle)}</strong>
        <span className="ds-browser-status-hint">{t(controlHint)}</span>
        {state?.demo_status === 'running' ? <progress aria-label={t('browserDemoRunning')} value={state.demo_step ?? 0} max={state.demo_total ?? 9} /> : null}
      </div>
      {state?.active ? <button type="button" className="ds-browser-control" disabled={!visible || !fresh || pending || controlBusy}
        aria-busy={controlBusy} onClick={() => void control(state.owner === 'user' ? 'agent' : 'user')}>
        {controlBusy ? <LoaderCircle className="ds-browser-control-spinner" size={14} /> : state.owner === 'user' ? <Play size={14} /> : <Hand size={14} />}
        {t(controlBusy ? 'browserControlSwitching' : state.assistance && state.owner === 'user' ? 'browserAssistContinue' : state.owner === 'user' ? state.task_running === false ? 'browserGiveControl' : 'browserReturnControl' : 'browserTakeControl')}
      </button> : null}
    </header>
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
            {onReturnToPages ? <button type="button" role="menuitem" className="ds-dock-menu-item" onClick={onReturnToPages}><ArrowLeft size={15} />{t('browserReturnToPages')}</button> : null}
            <button type="button" role="menuitem" className="ds-dock-menu-item" disabled={!userControls} onClick={() => action({ action: 'screenshot' })}><Camera size={15} />{t('browserSaveEvidence')}</button>
            <button type="button" role="menuitem" className="ds-dock-menu-item" disabled={!userControls} onClick={() => action({ action: state?.video_recording ? 'video_stop' : 'video_start' })}><Video size={15} />{t(state?.video_recording ? 'browserVideoStop' : 'browserVideoStart')}</button>
            <button type="button" role="menuitem" className="ds-dock-menu-item" disabled={!userControls} onClick={() => action({ action: state?.recording ? 'record_stop' : 'record_start' })}><Film size={15} />{t(state?.recording ? 'browserFinishRecording' : 'browserRecordSteps')}</button>
            <div className="ds-browser-menu-divider" role="separator" />
            {filePath && isHtmlPreviewPath(filePath) && onOpenFileInEditor ? <button type="button" role="menuitem" className="ds-dock-menu-item" onClick={() => onOpenFileInEditor(filePath)}><FileCode2 size={15} />{t('browserEditSource')}</button> : null}
            <button type="button" role="menuitem" className="ds-dock-menu-item" onClick={() => setDetails(true)}><Settings2 size={15} />{t('browserSettingsAndHistory')}</button>
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
    {waitingPreview ? <div className="ds-browser-notice"><span>{t('browserPreviewWaiting')}</span><button disabled={!userControls} onClick={() => void openPreview(waitingPreview.url, waitingPreview.filePath)}>{t('browserOpen')}</button><button aria-label={t('browserDismissPreview')} onClick={() => setWaitingPreview(null)}><X size={13} /></button></div> : null}
    {inspect || notice ? <div className="ds-browser-notice" role="status"><span>{inspect ? t('browserPickInstruction') : notice}</span><button aria-label={t('browserDismissPreview')} onClick={() => { setInspect(false); setNotice('') }}><X size={13} /></button></div> : null}
    {error || connectionError || state?.error ? <div role="alert" className="ds-browser-error">{error || connectionError || state?.error}</div> : null}
    <div className="ds-browser-content">
      {image && state?.active ? <BrowserViewport image={image} enabled={!!userControls && !details && !more} resizeEnabled={!!userControls && !details && !more && !state.video_recording} generation={state.generation ?? 0}
        inspect={inspect && canInspect} onInspectCancel={() => setInspect(false)} width={state.viewport?.width ?? 1200} height={state.viewport?.height ?? 760} label={t('browserLiveView')}
        send={async (body) => {
          if (body.kind === 'pick') {
            const result = await browserRequest<{ pick?: unknown; url?: string }>(threadId, '/input', body)
            const parsed = parsePreviewPickConsoleMessage(PREVIEW_PICK_CONSOLE_PREFIX + JSON.stringify({ type: 'pick', payload: result.pick }))
            if (alive.current && parsed?.type === 'pick' && filePath && result.url?.split('#')[0] === state.url?.split('#')[0]) {
              onPreviewPick?.({ ...parsed.payload, filePath }); setInspect(false); setNotice(t('browserPickAdded'))
            }
            return {}
          }
          if (body.kind !== 'resize') return browserRequest(threadId, '/input', body)
          setPending(true)
          try {
            const result = await browserRequest<{ text?: string }>(threadId, '/input', body)
            apply(await browserRequest<BrowserState>(threadId, '/view'))
            return result
          } finally { if (alive.current) setPending(false) }
        }} onError={setError} /> :
        <div className="ds-browser-empty"><Globe2 size={28} strokeWidth={1.3} /><h3>{t(pending ? 'browserStarting' : 'browserStartTitle')}</h3><p>{t('browserStartHint')}</p><button className={button} onClick={() => setDetails(true)}>{t('browserSessionSettings')}</button></div>}
      {details ? <section className="ds-browser-details" aria-label={t('browserSettingsAndHistory')}>
        <header className="ds-dock-header"><button ref={detailsButton} className="ds-dock-action" aria-label={t('browserCloseDetails')} onClick={() => { setDetails(false); if (!state?.active) onReturnToPages?.(); else menuButton.current?.focus() }}><ArrowLeft size={15} /></button><strong>{t('browserSettingsAndHistory')}</strong></header>
        <div className="ds-browser-details-body">
        {state?.demo_status && state.demo_status !== 'idle' ? <p role="status" className="mb-3 text-xs text-ds-muted">{t(state.demo_status === 'passed' ? 'browserDemoPassed' : state.demo_status === 'running' ? 'browserDemoRunning' : 'browserDemoStopped')}</p> : null}
        <button className={button} disabled={pending || state?.demo_status === 'running' || state?.workflow_recording || userControls}
          onClick={() => { setArtifactImage(null); void perform('/demo', {}) }}><Play size={13} />{t('browserRunDemo')}</button>
    <details className="mb-3 text-xs">
      <summary className="cursor-pointer py-2">{t('browserElementActions')}</summary>
      <div className="flex flex-col gap-2">
        <input className="rounded border border-ds-border bg-transparent p-2" placeholder={t('browserElementTarget')} value={selector} onChange={(e) => setSelector(e.target.value)} />
        <input className="rounded border border-ds-border bg-transparent p-2" placeholder={t('browserElementValue')} value={text} onChange={(e) => setText(e.target.value)} />
        <div className="flex gap-2">
          <button className={button} disabled={!userControls || pending || !selector} onClick={() => action({ action: 'fill', selector, text })}>{t('browserFill')}</button>
          <button className={button} disabled={!userControls || pending || !selector} onClick={() => action({ action: 'click', selector })}>{t('browserClick')}</button>
          <button className={button} disabled={!userControls || pending || !text.trim()} onClick={() => action({ action: 'check_text', text, timeout_ms: 3000 })}>{t('browserCheckText')}</button>
        </div>
        {dom ? <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded bg-ds-surface p-2">{dom}</pre> : null}
      </div>
    </details>
    <BrowserSessionSettings threadId={threadId} active={!!state?.active} userControls={!!userControls} recording={!!state?.workflow_recording} />
    <div className="text-xs font-semibold">{t('browserEvidence')}</div>
    <p className="my-2 text-xs text-ds-muted">{t('browserVideoHint')}</p>
    {state?.video_error ? <p role="alert" className="text-xs text-red-500">{state.video_error}</p> : null}
    <button className={button} disabled={pending || state?.video_recording || state?.demo_status === 'running' || (!state?.artifacts.length && !state?.log.length)} onClick={() => {
      setPending(true)
      setError('')
      void browserRequest<{ path: string }>(threadId, '/export', {})
        .then((result) => window.dsGui.showItemInFolder(result.path))
        .catch((e: Error) => setError(e.message)).finally(() => setPending(false))
    }}>{t('browserExportEvidence')}</button>
    <div className="my-2 flex flex-wrap gap-2">{state?.artifacts.map((artifact, index) =>
      <button key={artifact.id} className={button} onClick={() => {
        void browserRequest<{ image: string }>(threadId, '/artifacts/' + artifact.id)
          .then((result) => setArtifactImage(result.image)).catch((e: Error) => setError(e.message))
      }}>{index + 1}. {artifact.id.endsWith('.webm') ? t('browserVideo') : artifact.id.endsWith('.gif') ? t('browserStepAnimation') : artifact.label === '失败现场' ? t('browserFailureEvidence') : t('browserSaveEvidence')}</button>
    )}</div>
    {artifactImage?.startsWith('data:video/') ? <video className="mb-3 w-full rounded-lg border border-ds-border" controls src={artifactImage} aria-label={t('browserVideo')} /> : artifactImage ? <img className="mb-3 w-full rounded-lg border border-ds-border" src={artifactImage} alt={t('browserEvidence')} /> : null}
    <ol className="space-y-1 text-xs text-ds-muted">{state?.log.map((entry, i) =>
      <li key={i}>{entry.success ? '✓' : '✕'} {entry.action}</li>
    )}</ol>
    <p className="mt-3 text-[11px] leading-relaxed text-ds-muted">{t('browserDemoDisclaimer')}</p>
        </div>
      </section> : null}
    </div>
  </div>
}
