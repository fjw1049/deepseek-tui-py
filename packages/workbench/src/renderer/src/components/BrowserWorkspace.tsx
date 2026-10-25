import { useCallback, useEffect, useId, useMemo, useRef, useState, type ComponentProps, type ReactElement, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { ArrowLeft, ArrowRight, ChevronDown, ChevronRight, Clapperboard, Copy, FolderOpen, RotateCw, Globe2, Plus, X, MoreHorizontal, Hand, Play, Video, Film, Square, Pencil, ExternalLink, Bug, FileCode2, LoaderCircle, GraduationCap, CircleStop } from 'lucide-react'
import type { ChatBlock } from '../agent/types'
import { extractDetectedDevPreviewUrls, formatDevPreviewUrlLabel } from '../lib/dev-preview-detection'
import { extractWebviewConsoleMessage, parsePreviewPickConsoleMessage, PREVIEW_PICK_CONSOLE_PREFIX, type PreviewElementPick } from '../lib/preview-element-picker'
import { localizeDevBrowserScreenshotError } from '../lib/dev-browser-screenshot-errors'
import { annotationContextNote, readAnnotationBarShown, writeAnnotationBarShown } from '../lib/browser-annotation'
import { BrowserAnnotation, type BrowserAnnotationHandle } from './browser-annotation/BrowserAnnotation'
import { BLANK_PAGE, activatePageTab, closePageTab, ensureBrowserSession, navigatePageTab, openPageTab, pageWebview, setPageDisplay, updatePageTab, useBrowserPagesStore, setBrowserInputBlocked } from '../store/browser-pages-store'
import { isHtmlPreviewPath } from '@shared/html-preview'
import { BrowserCookieSync, type CookieSyncState } from './BrowserCookieSync'
import { BrowserRecordingPreview, type BrowserRecording } from './BrowserRecordingPreview'
import { BrowserDemoActivity, type DemoFailure, type DemoReview, type DemoStep } from './BrowserDemoActivity'
import { BrowserViewport } from './BrowserViewport'
import { formatAutomationApiError } from '../lib/automation-runtime-client'
import { DEFAULT_DEV_PREVIEW_URL, normalizeBrowseUrlInput } from '@shared/dev-preview-url'
import { useLightDismiss } from '../hooks/use-light-dismiss'
import { copyText } from '../lib/copy-text'
import { consumeBrowserDemoRequest, setBrowserDemoActive, useBrowserDemoStore } from '../store/browser-demo-store'
import './browser-workspace.css'
import { respondToAssistance } from './BrowserAssistance'
import type { Assistance } from './BrowserAssistanceCard'

const FFMPEG_INSTALL_COMMAND = 'brew install ffmpeg'

/** Seconds since `active` last turned on, counted here (the runtime does not report a start time). */
function useElapsedSeconds(active: boolean): number {
  const [startedAt, setStartedAt] = useState<number | null>(null)
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!active) { setStartedAt(null); return }
    const start = Date.now()
    setStartedAt(start); setNow(start)
    const timer = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [active])
  return startedAt === null ? 0 : Math.max(0, Math.floor((now - startedAt) / 1000))
}

function formatClock(seconds: number): string {
  return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`
}

function BrowserPointerIcon(): ReactElement {
  return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinejoin="round" aria-hidden="true">
    <path d="M5.5 3.5 18.5 10.5 11.8 12.8 9.5 20Z" />
  </svg>
}

type BrowserState = {
  persistent?: boolean
  cookie_sync?: CookieSyncState
  assistance?: Assistance | null
  active: boolean; url?: string; generation?: number; transferring?: boolean
  task_paused?: boolean; task_running?: boolean; task_pausing?: boolean
  viewport?: { width: number; height: number }
  tabs?: { tab_id: string; title: string; url: string; active: boolean; popup?: boolean }[]
  image?: string | null; video_recording?: boolean; video_error?: string | null
  owner: 'agent' | 'user' | 'stopped'; recording: boolean
  recording_error?: string | null; recording_pending_save?: boolean
  activity?: string; demo_status?: string; healthy?: boolean; workflow_recording?: boolean
  workflow_tabs?: string[]
  /** Demonstration tabs the recorder could not attach to, with the reason. */
  workflow_tab_errors?: Record<string, string>
  error: string | null; log: { action: string; success: boolean }[]
  artifacts: { id: string; label: string; path: string }[]
  scene?: { scene_id: string; tab_id: string; document_id: string; viewport_epoch: number }
  view_sequence?: number
  frame_status?: 'ready' | 'busy' | 'changed'
  capabilities?: { video?: { ready: boolean; max_seconds?: number } }
  unresolved?: ActionReceipt[]
  dialog?: { id: string; type: string; message: string } | null
  loading?: boolean
  surface?: 'native' | 'headless'
  file_chooser?: { id: string; mode: string } | null
  downloads?: { id: string; state: string; filename: string; received_bytes: number; path?: string }[]
}

type ActionReceipt = { action?: string; target_url?: string; action_id: string; execution: string; effect?: string; reconciliation?: unknown }
type ActionResult = { success?: boolean; content?: unknown; receipt?: ActionReceipt; dialog?: BrowserState['dialog']; artifact?: BrowserState['artifacts'][number] | null }
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

/** The browser before a conversation exists; agents never act in it. */
export const PREVIEW_BROWSER_ID = 'workbench-preview'

type BrowserWorkspaceProps = {
  threadId: string | null; visible?: boolean; blocks?: ChatBlock[]
  preferredUrl?: string | null; preferredFilePath?: string | null; externalError?: string | null
  onPreferredUrlConsumed?: () => void; onExternalErrorConsumed?: () => void
  onPreviewPick?: (pick: PreviewElementPick) => void
  onAttachImage?: (file: File, contextNote: (path: string) => string) => Promise<boolean>
  onOpenFileInEditor?: (path: string) => void
  onDemonstrationSaved?: (message: string) => void
}

/** One browser shared by the user and the agent: previews, browsing and automation. */
export function BrowserWorkspace({ threadId: conversationId, visible = true, blocks = [], preferredUrl, preferredFilePath,
  onPreferredUrlConsumed, externalError, onExternalErrorConsumed, onPreviewPick, onAttachImage, onOpenFileInEditor,
  onDemonstrationSaved }: BrowserWorkspaceProps): ReactElement {
  const threadId = conversationId ?? PREVIEW_BROWSER_ID
  const [dialogAnswer, setDialogAnswer] = useState('')
  const { t } = useTranslation('common')
  const [state, setState] = useState<BrowserState | null>(null)
  const [polled, setPolled] = useState(false)
  useEffect(() => { setDialogAnswer('') }, [state?.dialog?.id])
  // Temporary sessions use the isolated runtime browser, never shared Workbench tabs.
  const remote = state?.persistent === false || state?.surface === 'headless' || !!state?.unresolved?.length || (!!state?.active && state.surface !== 'native')
  const viewSuffix = remote ? '/view' : ''
  const session = useBrowserPagesStore(store => store.sessions[threadId])
  // Shown browsers always have a page; hidden ones may have been closed to save memory.
  const hasSession = !!session
  const nativeAllowed = !!state && state.persistent !== false && state.surface !== 'headless'
  useEffect(() => {
    if (visible && nativeAllowed && !hasSession) ensureBrowserSession(threadId)
  }, [threadId, visible, hasSession, nativeAllowed])
  const activeTab = session?.tabs.find(tab => tab.id === session.activeTabId)
  const [image, setImage] = useState<string | null>(null)
  const [frameFresh, setFrameFresh] = useState(false)
  const [url, setUrl] = useState('')
  const [error, setError] = useState('')
  const [connectionError, setConnectionError] = useState('')
  const [pending, setPending] = useState(false)
  const [demoChanging, setDemoChanging] = useState<'start' | 'stop' | null>(null)
  // Demonstration failures are about the recording, not the connection; they get their own card.
  const [demoFailure, setDemoFailure] = useState<DemoFailure | null>(null)
  // A finished demonstration waits here: the user may check its steps, then add it to the chat.
  const [demoReview, setDemoReview] = useState<DemoReview | null>(null)
  const [controlTarget, setControlTarget] = useState<'agent' | 'user' | 'stopped' | null>(null)
  const [more, setMore] = useState(false)
  const [recordChoice, setRecordChoice] = useState(false)
  useEffect(() => { if (!more) setRecordChoice(false) }, [more])
  const menuDetailId = useId()
  const controlOptionsId = useId()
  const [controlOpen, setControlOpen] = useState(false)
  const controlRoot = useRef<HTMLDivElement>(null)
  const controlButton = useRef<HTMLButtonElement>(null)
  useLightDismiss({ open: controlOpen, refs: [controlRoot], onDismiss: () => {
    if (controlRoot.current?.contains(document.activeElement)) controlButton.current?.focus()
    setControlOpen(false)
  } })
  const [cookieSettings, setCookieSettings] = useState(false)
  const [cookieAnchor, setCookieAnchor] = useState<DOMRect | null>(null)
  const [cookieUpdate, setCookieUpdate] = useState(0)
  const menuRoot = useRef<HTMLDivElement>(null)
  const menuButton = useRef<HTMLButtonElement>(null)
  const [fresh, setFresh] = useState(false)
  // Previews wait for the first answer, which tells whether the page is local or remote.
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
  const [annotationBarShown, setAnnotationBarShownState] = useState(readAnnotationBarShown)
  const annotation = useRef<BrowserAnnotationHandle>(null)
  const annotationButton = useRef<HTMLButtonElement>(null)
  const setAnnotationBarShown = useCallback((shown: boolean): void => {
    const area = pageArea.current
    const button = annotationButton.current
    if (area && button) {
      const bounds = area.getBoundingClientRect()
      const target = button.getBoundingClientRect()
      const zoom = area.offsetWidth ? bounds.width / area.offsetWidth : 1
      area.style.setProperty('--annotation-collapse-x', `${(target.left + target.width / 2 - bounds.left) / (zoom || 1)}px`)
      area.style.setProperty('--annotation-collapse-bottom', `${(bounds.bottom - target.top - target.height / 2) / (zoom || 1)}px`)
      if (!shown) button.focus({ preventScroll: true })
    }
    writeAnnotationBarShown(shown)
    setAnnotationBarShownState(shown)
  }, [])
  const [notice, setNotice] = useState('')
  const [savedRecording, setSavedRecording] = useState<{ threadId: string; artifact: BrowserRecording } | null>(null)
  const [recordingPreview, setRecordingPreview] = useState<{ threadId: string; artifact: BrowserRecording } | null>(null)
  const [recordingStopping, setRecordingStopping] = useState(false)
  useEffect(() => {
    if (state?.video_recording || state?.recording) { setSavedRecording(null); setDemoReview(null); setDemoFailure(null) }
  }, [state?.video_recording, state?.recording, threadId])
  const recordingResult = savedRecording?.threadId === threadId ? savedRecording.artifact : null
  const latestRecording = [...(state?.artifacts ?? [])].reverse().find(item => /\.(gif|webm)$/i.test(item.id))

  // A saved file stays reachable while its notice is the one on screen.
  const [savedNotice, setSavedNotice] = useState<{ notice: string; path: string } | null>(null)
  useEffect(() => {
    if (!notice) return
    const timer = window.setTimeout(() => setNotice(''), 4000)
    return () => window.clearTimeout(timer)
  }, [notice])
  const detectedUrls = useMemo(() => extractDetectedDevPreviewUrls(blocks), [blocks])
  const filePath = remote ? (state?.url ? previewFiles[state.url.split('#')[0]] : undefined) : activeTab?.filePath ?? undefined
  const inspectedPage = remote ? state?.url : activeTab?.id
  useEffect(() => { setInspect(false) }, [visible, inspectedPage, state?.generation, state?.owner])
  useEffect(() => { if (externalError) { setError(externalError); onExternalErrorConsumed?.() } }, [externalError, onExternalErrorConsumed])
  const userControls = visible && fresh && state?.owner === 'user' && !state.transferring && !pending
  const screenRecording = !!(state?.recording || state?.video_recording || state?.recording_pending_save)
  // Screen recording and demonstration share the activity card, so only one runs at a time.
  const recordingBusy = screenRecording || recordingStopping
  const demoBusy = !!state?.workflow_recording || demoChanging !== null
  const videoUnavailable = state?.capabilities?.video?.ready === false
  const videoSeconds = useElapsedSeconds(!!state?.video_recording)
  const gifSeconds = useElapsedSeconds(!!state?.recording)
  const demoSeconds = useElapsedSeconds(!!state?.workflow_recording)
  const demoRequest = useBrowserDemoStore(store => store.request)
  // A menu entry with a one-line explanation; the label stays its accessible name.
  const menuDetailItem = (id: string, icon: ReactNode, label: string, detail: string, props: ComponentProps<'button'>, trailing?: ReactNode): ReactElement =>
    <button type="button" role="menuitem" className="ds-dock-menu-item ds-browser-menu-detail" aria-label={label} aria-describedby={`${menuDetailId}-${id}`} {...props}>
      <span className="ds-browser-menu-detail__icon" aria-hidden="true">{icon}</span><span className="ds-browser-menu-detail__text"><span>{label}</span><small id={`${menuDetailId}-${id}`}>{detail}</small></span>{trailing}
    </button>
  const canNavigate = visible && fresh && !state?.unresolved?.length && !pending && !state?.transferring && (!state?.active || userControls)
  // The user browses Workbench tabs directly unless the agent is working in them.
  const agentWorking = !!state?.active && state.owner === 'agent' && (!!state.task_running || state.demo_status === 'running')
  const capturePending = !remote && !!state?.workflow_recording && !(state.workflow_tabs ?? []).includes(activeTab?.id ?? '')
  const captureError = capturePending ? state?.workflow_tab_errors?.[activeTab?.id ?? ''] : undefined
  // Recording transitions, automation and uncertain results must also block native input.
  const inputHeld = demoChanging || capturePending || agentWorking || !!state?.transferring || !!state?.unresolved?.length || (lastReceipt?.execution === 'unknown' && !lastReceipt.reconciliation)
  const blockNativeInput = !state || !fresh || state.healthy === false || !!inputHeld
  useEffect(() => { setBrowserInputBlocked(threadId, blockNativeInput) }, [threadId, blockNativeInput, hasSession])
  const canBrowse = visible && !!state && !blockNativeInput
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  const pageUrl = remote ? state?.url : activeTab?.url
  // Workspace HTML previews pick against their source file; any other web page picks by URL.
  const pickSource = useMemo(() => filePath && isHtmlPreviewPath(filePath) ? { filePath }
    : pageUrl && /^(https?|file):/i.test(pageUrl) ? { filePath: '', pageUrl } : null, [filePath, pageUrl])
  const canInspect = !!pickSource && !!onPreviewPick
  useEffect(() => { if (pageUrl) setUrl(pageUrl === BLANK_PAGE ? '' : pageUrl) }, [pageUrl])
  const knownArtifacts = useRef<{ threadId: string; ids: Set<string> } | null>(null)
  useEffect(() => {
    if (!state) return
    const previous = knownArtifacts.current
    const artifacts = state.artifacts ?? []
    knownArtifacts.current = { threadId, ids: new Set(artifacts.map(item => item.id)) }
    if (!previous || previous.threadId !== threadId) return
    const saved = [...artifacts].reverse().find(item => !previous.ids.has(item.id) && /\.(gif|webm)$/i.test(item.id))
    if (saved) {
      setSavedRecording({ threadId, artifact: saved })
    }
  }, [state, threadId, t])
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
    setState(next); if (next.image) setImage(next.image)
  }, [])
  useEffect(() => {
    if (!visible) return
    let disposed = false
    let timer: ReturnType<typeof setTimeout>
    const poll = async (): Promise<void> => {
      let delay = 600
      const started = performance.now()
      try {
        const next = await browserRequest<BrowserState>(threadId, viewSuffix)
        if (!disposed) {
          apply(next); setConnectionError('')
          // Streamed frames make an unchanged view cheap, so the human view polls near 30 fps.
          delay = !viewSuffix || !next.active ? 600 : next.owner === 'user' ? Math.max(16, 33 - (performance.now() - started)) : 300
        }
      } catch (e) { if (!disposed) { setFresh(false); setFrameFresh(false); setConnectionError(e instanceof Error ? e.message : String(e)) } }
      finally { if (!disposed) { setPolled(true); timer = setTimeout(() => void poll(), delay) } }
    }
    void poll(); return () => { disposed = true; clearTimeout(timer) }
  }, [threadId, visible, apply, viewSuffix])
  const perform = useCallback(async (suffix: string, body: unknown): Promise<boolean> => {
    setError(''); setPending(true)
    try {
      const payload = suffix === '/action' && state?.active ? {
        ...(!remote && activeTab?.id ? { tab_id: activeTab.id } : {}),
        ...(body as Record<string, unknown>), generation: state.generation
      } : body
      const result = await browserRequest<ActionResult>(threadId, suffix, payload)
      if (!alive.current) return false
      if (result.artifact && /\.(gif|webm)$/i.test(result.artifact.id)) {
        setSavedRecording({ threadId, artifact: result.artifact })
      } else if (result.artifact) {
        const saved = t('browserArtifactSaved', { name: result.artifact.label || result.artifact.id })
        setNotice(saved); setSavedNotice({ notice: saved, path: result.artifact.path })
      }
      if (result.receipt) setLastReceipt(result.receipt)
      if (result.dialog) setState(previous => previous ? { ...previous, dialog: result.dialog } : previous)
      if (result.success === false) setError(typeof result.content === 'string' ? result.content : JSON.stringify(result.content))
      try { apply(await browserRequest<BrowserState>(threadId, viewSuffix)); setConnectionError('') }
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
  }, [threadId, apply, state?.active, state?.generation, t, viewSuffix, remote, activeTab?.id])
  const action = useCallback((body: unknown): void => { void perform('/action', body) }, [perform])
  async function stopRecording(): Promise<void> {
    setRecordingStopping(true)
    try {
      if (state?.video_recording) await perform('/action', { action: 'video_stop' })
      if (state?.recording || state?.recording_pending_save) await perform('/action', { action: 'record_stop' })
    } finally { if (alive.current) setRecordingStopping(false) }
  }

  async function stopLoading(): Promise<void> {
    if (!remote) { try { pageWebview(activeTab?.id)?.stop() } catch { /* not attached yet */ } return }
    try { await browserRequest(threadId, '/input', { kind: 'stop', generation: state?.generation ?? 0 }) }
    catch (e) { setError(e instanceof Error ? e.message : String(e)) }
  }
  // The runtime drives the visible tabs once bound; without it they still browse locally.
  const attachedAt = useRef(0)
  const [attachRetry, setAttachRetry] = useState(0)
  useEffect(() => {
    if (!visible || !fresh || state?.active) return
    const timer = window.setTimeout(() => {
      attachedAt.current = Date.now()
      // Workbench may not have announced its bridge yet; try again after a pause.
      void browserRequest<BrowserState>(threadId, '/attach', {}).then(apply).catch(() => setAttachRetry(count => count + 1))
    }, Math.max(0, 5000 - (Date.now() - attachedAt.current)))
    return () => window.clearTimeout(timer)
  }, [visible, fresh, state?.active, threadId, apply, attachRetry])
  // The page layer places the active tab under this transparent area.
  const pageArea = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const release = (): void => { if (useBrowserPagesStore.getState().display?.browserId === threadId) setPageDisplay(null) }
    const area = pageArea.current
    const layer = document.querySelector<HTMLElement>('.ds-browser-page-layer')
    if (!visible || !nativeAllowed || remote || !area || !layer) { release(); return }
    let frame = 0
    let until = 0
    const measure = (): void => {
      const box = area.getBoundingClientRect()
      const origin = layer.getBoundingClientRect()
      // Client rects include the UI scale (body zoom); the layer's own pixels do not.
      const scale = layer.offsetWidth ? origin.width / layer.offsetWidth : 1
      setPageDisplay({ browserId: threadId, rect: { top: Math.round((box.top - origin.top) / scale),
        left: Math.round((box.left - origin.left) / scale), width: Math.round(box.width / scale), height: Math.round(box.height / scale) } })
      if (performance.now() < until) frame = requestAnimationFrame(measure)
    }
    // Panel slides and resizes move the area; follow it for a moment after each change.
    const follow = (): void => { until = performance.now() + 450; cancelAnimationFrame(frame); frame = requestAnimationFrame(measure) }
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(follow)
    observer?.observe(area); observer?.observe(layer)
    window.addEventListener('resize', follow)
    document.addEventListener('transitionend', follow, true)
    follow()
    return () => {
      observer?.disconnect(); window.removeEventListener('resize', follow)
      document.removeEventListener('transitionend', follow, true); cancelAnimationFrame(frame); release()
    }
  }, [visible, nativeAllowed, remote, threadId])
  useEffect(() => {
    if (inputHeld) try { pageWebview(activeTab?.id)?.blur() } catch { /* not attached yet */ }
  }, [inputHeld, activeTab?.id])
  // Element picking on a native tab: the injected picker reports over console messages.
  useEffect(() => {
    const webview = remote ? null : pageWebview(activeTab?.id)
    if (!inspect || !webview || !pickSource) return
    // The main process runs the picker in the main frame, so it arms while the page is still loading.
    const run = (action: 'arm' | 'disarm'): void => {
      try { void window.dsGui.runDevBrowserPicker(webview.getWebContentsId(), action).catch(() => {}) } catch { /* not attached yet */ }
    }
    const arm = (): void => run('arm')
    const onMessage = (event: Event): void => {
      const message = extractWebviewConsoleMessage(event)
      const parsed = message && message.includes(PREVIEW_PICK_CONSOLE_PREFIX) ? parsePreviewPickConsoleMessage(message) : null
      if (parsed?.type === 'cancel') setInspect(false)
      else if (parsed?.type === 'pick') {
        onPreviewPick?.({ ...parsed.payload, ...pickSource })
        // With the annotation bar, a pick ends selection mode (the bar returns to rest).
        if (onAttachImage) { setInspect(false); setNotice(t('browserPickAdded')) }
      }
    }
    arm()
    webview.addEventListener('dom-ready', arm)
    webview.addEventListener('console-message', onMessage)
    return () => {
      webview.removeEventListener('dom-ready', arm)
      webview.removeEventListener('console-message', onMessage)
      run('disarm')
    }
  }, [inspect, remote, activeTab?.id, pickSource, onPreviewPick, onAttachImage, t])
  async function refreshBrowser(): Promise<void> {
    setPending(true); setFrameFresh(false)
    try {
      if (state?.active) await browserRequest(threadId, '/action', { action: 'observe', generation: state.generation })
      apply(await browserRequest<BrowserState>(threadId, viewSuffix))
      setLastReceipt(null); setError(''); setConnectionError('')
    } catch (e) { setConnectionError(e instanceof Error ? e.message : String(e)) }
    finally { setPending(false) }
  }
  const demoErrorMessage = (message: string): string => message.includes('incomplete browser capture') ? t('browserDemoIncomplete') : message
  /** A saved demonstration waits in the activity card for the user to add it to the chat. */
  function demonstrationEnded(saved: { recordingId: string; steps: number }): void {
    if (onDemonstrationSaved) setDemoReview({ id: saved.recordingId, count: saved.steps, message: t('browserDemoMessage', { id: saved.recordingId, steps: saved.steps }), open: false })
    else setNotice(t('browserDemoSavedNotice'))
  }
  async function demonstrate(): Promise<void> {
    const finishing = !!state?.workflow_recording
    if (!finishing && recordingBusy) { setNotice(t('browserDemoBusyRecording')); return }
    setError(''); setDemoFailure(null); setPending(true); setDemoChanging(finishing ? 'stop' : 'start')
    // A new demonstration replaces whatever result the activity card was showing.
    if (!finishing) { setDemoReview(null); setSavedRecording(null) }
    try {
      try {
        if (finishing) {
          const saved = await browserRequest<{ recordingId: string; steps: number }>(threadId, '/workflows', { action: 'stop' })
          if (alive.current) demonstrationEnded(saved)
        } else await browserRequest(threadId, '/workflows', { action: 'start', generation: state?.generation,
          ...(!remote && activeTab ? { tab_id: activeTab.id } : {}) })
      } catch (e) {
        if (alive.current) setDemoFailure({ stage: finishing ? 'save' : 'start', message: demoErrorMessage(e instanceof Error ? e.message : String(e)) })
      }
      // Refresh after a failure too: a failed stop has still ended the recording.
      if (alive.current) apply(await browserRequest<BrowserState>(threadId, viewSuffix))
    } catch { /* The next poll shows the current state. */ }
    finally { if (alive.current) { setPending(false); setDemoChanging(null) } }
  }
  async function toggleDemoSteps(): Promise<void> {
    if (!demoReview) return
    if (demoReview.open || demoReview.steps !== undefined) { setDemoReview({ ...demoReview, open: !demoReview.open }); return }
    setDemoReview({ ...demoReview, open: true, steps: null, stepsError: false })
    try {
      const doc = await browserRequest<{ steps: DemoStep[] }>(threadId, '/workflows', { action: 'preview', recording_id: demoReview.id })
      if (alive.current) setDemoReview(current => current?.id === demoReview.id ? { ...current, steps: doc.steps } : current)
    } catch {
      // Left unloaded, so showing the steps again retries.
      if (alive.current) setDemoReview(current => current?.id === demoReview.id ? { ...current, steps: undefined, stepsError: true } : current)
    }
  }
  useEffect(() => { if (conversationId) setBrowserDemoActive(conversationId, !!state?.workflow_recording) }, [conversationId, state?.workflow_recording])
  // The composer's demonstrate button lands here once this conversation's browser is showing.
  useEffect(() => {
    if (!demoRequest || demoRequest.threadId !== conversationId || !visible || !state || !fresh || pending) return
    consumeBrowserDemoRequest(demoRequest.id)
    if (userControls) void demonstrate()
    else setNotice(t('browserDemoNeedsControl'))
  }, [demoRequest, conversationId, visible, state, fresh, pending, userControls]) // eslint-disable-line react-hooks/exhaustive-deps
  async function control(owner: 'agent' | 'user' | 'stopped'): Promise<void> {
    // Returning control saves an open demonstration without sending another query; its result shows like a finished one.
    const demonstrating = owner === 'agent' && !!state?.workflow_recording
    setPending(true); setControlTarget(owner); setError(''); transferring.current = true
    try {
      if (state?.assistance && owner !== 'stopped') {
        await respondToAssistance(threadId, state.assistance.id, owner === 'user' ? 'takeover' : 'continue')
        transferring.current = false
        apply(await browserRequest<BrowserState>(threadId, viewSuffix))
        return
      }
      const next = await browserRequest<BrowserState & { demonstration?: { recordingId: string; steps: number } | { error: string } }>(threadId, '/control', { owner, generation: state?.generation })
      transferring.current = false
      if (!alive.current) return
      apply(next)
      const ended = next.demonstration
      if (ended && 'error' in ended) setDemoFailure({ stage: 'save', message: demoErrorMessage(ended.error) })
      else if (ended) demonstrationEnded(ended)
      else if (demonstrating) setNotice(t('browserDemoSavedNotice'))
      if (owner === 'user' && next.unresolved?.length) {
        await browserRequest(threadId, '/action', { action: 'observe', generation: next.generation })
        apply(await browserRequest<BrowserState>(threadId, viewSuffix))
        setLastReceipt(null)
        setControlOpen(true)
      }
    } catch (e) { if (alive.current) setError(e instanceof Error ? e.message : String(e)) }
    finally { transferring.current = false; if (alive.current) { setPending(false); setControlTarget(null) } }
  }
  const openPreview = useCallback(async (target: string, source?: string | null): Promise<void> => {
    const normalized = normalizeBrowseUrlInput(target)
    if (!normalized) { setError(t('browserInvalidUrl')); return }
    if (!remote) {
      if (agentWorking) { setWaitingPreview({ url: normalized, filePath: source }); return }
      const tabs = useBrowserPagesStore.getState().sessions[threadId]?.tabs ?? []
      const existing = tabs.find(tab => tab.url === normalized)
      const blank = tabs.find(tab => tab.id === useBrowserPagesStore.getState().sessions[threadId]?.activeTabId && tab.url === BLANK_PAGE)
      if (existing) {
        activatePageTab(threadId, existing.id)
        if (source) updatePageTab(threadId, existing.id, { filePath: source })
      } else if (blank) {
        navigatePageTab(threadId, blank.id, normalized, source ?? null)
      } else openPageTab(threadId, normalized, { filePath: source ?? null })
      setWaitingPreview(null)
      return
    }
    if (state?.active && !userControls) { setWaitingPreview({ url: normalized, filePath: source }); return }
    const existing = state?.tabs?.find(tab => tab.url === normalized)
    const opened = await perform('/action', existing ? { action: 'switch_tab', tab_id: existing.tab_id } :
      { action: state?.active ? 'new_tab' : 'open', url: normalized })
    if (opened && source) setPreviewFiles(current => ({ ...current, [normalized.split('#')[0]]: source }))
    if (opened) setWaitingPreview(null)
  }, [state, userControls, perform, t, remote, agentWorking, threadId])
  useEffect(() => {
    if (!preferredUrl) { lastPreferred.current = null; return }
    if (!visible || !polled || (remote && (!fresh || pending)) || lastPreferred.current === preferredUrl) return
    lastPreferred.current = preferredUrl
    void openPreview(preferredUrl, preferredFilePath)
    onPreferredUrlConsumed?.()
  }, [visible, fresh, polled, preferredUrl, preferredFilePath, pending, openPreview, onPreferredUrlConsumed, remote])
  async function openDevTools(): Promise<void> {
    if (!remote) { try { pageWebview(activeTab?.id)?.openDevTools() } catch { /* not attached yet */ } return }
    try {
      const result = await browserRequest<{ url: string }>(threadId, '/input', { kind: 'devtools', generation: state?.generation ?? 0 })
      await window.dsGui.openExternal(result.url)
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
  }
  const captureForAnnotation = useCallback(async (): Promise<string> => {
    if (remote) {
      const snapshot = await browserRequest<BrowserState>(threadId, '/view')
      if (!snapshot.image) throw new Error(t('annotationCaptureFailed'))
      return snapshot.image
    }
    const webview = pageWebview(activeTab?.id)
    if (!webview) throw new Error(t('annotationCaptureFailed'))
    const result = await window.dsGui.captureDevBrowserScreenshot(webview.getWebContentsId())
    if (result.ok) return result.dataUrl
    const message = localizeDevBrowserScreenshotError(result.message, t)
    throw new Error(message === t('browserScreenshotFailed') ? t('annotationCaptureFailed') : message)
  }, [remote, threadId, activeTab?.id, t])
  function navigate(): void {
    const value = url.trim()
    if (!value) { if (!remote && activeTab && activeTab.url !== BLANK_PAGE) loadInTab(activeTab.id, BLANK_PAGE); return }
    const isSearch = /\s/.test(value) || (!/[.:/]/.test(value) && !/^\d+$/.test(value) && value !== 'localhost')
    const target = isSearch ? `https://www.google.com/search?q=${encodeURIComponent(value)}` : normalizeBrowseUrlInput(value)
    if (!target) { setError(t('browserInvalidUrl')); return }
    if (!remote) { if (activeTab) loadInTab(activeTab.id, target); return }
    action({ action: 'open', url: target })
  }
  function loadInTab(tabId: string, target: string): void {
    // Typed addresses have no workspace source.
    navigatePageTab(threadId, tabId, target)
  }
  const nativeHistory = (method: 'canGoBack' | 'canGoForward'): boolean => {
    try { return !!pageWebview(activeTab?.id)?.[method]() } catch { return false }
  }
  const controlBusy = controlTarget !== null || !!state?.transferring || !!state?.task_pausing
  const unresolvedReceipt = state?.unresolved?.[0] || (lastReceipt?.execution === 'unknown' && !lastReceipt.reconciliation ? lastReceipt : null)
  const reviewActionLabel = ({ click: 'browserClick', fill: 'browserFill', open: 'browserOpen', reload: 'browserReload' } as Record<string, string>)[unresolvedReceipt?.action ?? '']
  const requiresReview = !!(unresolvedReceipt || state?.dialog || state?.file_chooser)
  const hasConnectionProblem = state?.healthy === false || !!(connectionError || state?.error)
  const needsAttention = !!(unresolvedReceipt || state?.dialog || state?.file_chooser || waitingPreview || error || connectionError || state?.error || state?.healthy === false)
  const needsHelp = state?.assistance?.status === 'pending'
  const controlTone = needsHelp || needsAttention ? 'attention' : state?.owner === 'user' ? 'human' : agentWorking ? 'agent' : 'idle'
  const showControlButton = !!state?.active && !(requiresReview && state.owner === 'user') && (!hasConnectionProblem || requiresReview)
    && !(state.owner === 'user' && state.task_running === false && !state.assistance)
  // Agent activity, a pending hand-over, or anything waiting on the user keeps the bar up even when its tools were hidden.
  const controlForced = controlTone === 'agent' || controlTone === 'attention' || showControlButton
  const controlTitle = controlTarget === 'user' ? 'browserPausing' : controlTarget === 'agent' ? 'browserResuming'
    : controlTarget === 'stopped' ? 'browserWorking' : state?.task_pausing ? 'browserTaskPausing'
    : state?.transferring ? 'browserWorking' : capturePending ? 'browserDemoAttaching' : requiresReview || needsHelp ? 'browserWaitingForYou' : hasConnectionProblem ? 'browserConnectionProblem' : !state?.active ? 'browserIdle'
    : state.owner === 'user' ? state.task_paused ? 'browserTaskPaused' : 'browserUserControl' : state.task_paused ? 'browserControlPaused'
    : !agentWorking && state.task_running === false ? 'browserAgentReady' : 'browserAgentControl'
  const controlHint = controlBusy ? 'browserControlSwitchHint' : unresolvedReceipt ? 'browserReviewHint' : requiresReview ? 'browserResponseHint' : hasConnectionProblem ? 'browserReconnectHint' : needsHelp ? 'browserControlHelpHint'
    : state?.owner === 'user' ? state.task_running || state.task_paused ? 'browserControlHumanHint' : 'browserControlHumanIdleHint'
    : agentWorking ? 'browserAgentHint' : 'browserControlReadyHint'
  const tabViews = remote
    ? (state?.tabs ?? []).map(tab => ({ id: tab.tab_id, title: tab.title, url: tab.url, active: tab.active }))
    : [...(session?.tabs ?? []).map(tab => ({ id: tab.id, title: tab.title, url: tab.url, active: tab.id === session?.activeTabId })),
      ...(state?.tabs ?? []).filter(tab => tab.popup).map(tab => ({ id: tab.tab_id, title: tab.title, url: tab.url, active: false }))]
  const agentTab = agentWorking ? state?.tabs?.find(tab => tab.active) : undefined
  const isPopup = (id: string): boolean => !!state?.tabs?.some(tab => tab.tab_id === id && tab.popup)
  const soleBlank = !remote && tabViews.length === 1 && tabViews[0]!.url === BLANK_PAGE
  const tabsEnabled = remote ? canNavigate : visible && !!state && !state.unresolved?.length
  const addressEnabled = remote ? canNavigate : canBrowse
  const loading = remote ? !!state?.loading : !!activeTab?.loading
  const canStop = loading && (remote ? visible && fresh && state?.owner === 'user' && !state.transferring : canBrowse)
  const pageOpen = !!activeTab && activeTab.url !== BLANK_PAGE
  const annotationReady = remote ? !!userControls && !!image : canBrowse && pageOpen
  const annotationSurface = !!onAttachImage && (remote ? !!image : pageOpen)
  const recordingForced = screenRecording || recordingStopping || !!recordingResult
  const demoForced = !!state?.workflow_recording || demoChanging === 'stop' || !!demoReview || !!demoFailure
  // A recording or demonstration card keeps the bar up even when its tools were hidden.
  const activityForced = recordingForced || demoForced
  // The agent's page cannot be annotated, so while it holds the page the bar carries only the status.
  const agentHolds = state?.owner === 'agent' && !annotationReady
  const annotationBarVisible = annotationSurface && !agentHolds && (annotationBarShown || inspect || controlForced || activityForced)
  // Without a page to annotate, the bar still carries the status whenever it matters.
  const statusBarOnly = !annotationBarVisible && (controlForced || activityForced)
  useEffect(() => {
    const area = pageArea.current
    const toolbar = area?.querySelector<HTMLElement>('.ds-annotation-toolbar')
    if (!area || !toolbar) return
    const measure = () => area.style.setProperty('--browser-toolbar-height', `${toolbar.offsetHeight}px`)
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(toolbar)
    return () => { observer.disconnect(); area.style.removeProperty('--browser-toolbar-height') }
  }, [annotationBarVisible, statusBarOnly, activityForced, inspectedPage, state?.generation, state?.owner])

  const pickHint = inspect && !annotationBarVisible
  // The picker swallows page clicks, so it must not stay armed while the agent drives the page.
  useEffect(() => { if (onAttachImage && !annotationReady) setInspect(false) }, [onAttachImage, annotationReady])
  const controlDetails = !!(error || waitingPreview || (unresolvedReceipt && userControls) || (state?.dialog && userControls) || (state?.file_chooser && userControls)
    || state?.downloads?.length || (hasConnectionProblem && (!requiresReview || state?.healthy === false)))
  const statusCopy = <span className="ds-browser-status-copy" role="status" aria-live="polite" aria-atomic="true">
          <strong><span className="ds-browser-status-dot" aria-hidden="true" />{t(controlTitle)}{needsAttention && !requiresReview && !hasConnectionProblem ? <span className="ds-browser-attention">{t('browserNeedsAttention')}</span> : state?.downloads?.length ? <span className="ds-browser-attention">{t('browserDownloads')}</span> : null}</strong>
        </span>
  // One card above the bar for whatever is recording: screen recording, else a demonstration.
  const activityCard = recordingForced ? <div className="ds-browser-recording-activity" role="group" aria-label={t('browserRecordingPanel')}>
    <div className="ds-browser-recording-activity__copy">
      <strong role="status">{recordingStopping ? <LoaderCircle size={14} className="ds-browser-control-spinner" /> : screenRecording ? <span className="ds-browser-recording-dot" /> : <Film size={15} />}
        {t(recordingStopping ? 'browserRecordingSaving' : state?.recording_pending_save ? 'browserRecordingUnsaved' : screenRecording ? 'browserRecordingChip' : 'browserRecordingSaved')}
        {state?.video_recording || state?.recording ? <span className="ds-browser-recording-time" aria-hidden="true">{formatClock(state.video_recording ? videoSeconds : gifSeconds)}</span> : null}
      </strong>
      <small>{t(recordingStopping ? 'browserRecordingSavingHint' : screenRecording ? state?.recording_pending_save ? 'browserRecordingRetryHint' : 'browserRecordScreenDetail' : 'browserRecordingSavedHint')}</small>
    </div>
    {screenRecording || recordingStopping ? <button type="button" className="ds-annotation-toolbar__primary" disabled={!userControls || recordingStopping} aria-busy={recordingStopping} onClick={() => void stopRecording()}>
      {!recordingStopping ? <Square size={12} fill="currentColor" /> : null}{t(recordingStopping ? 'browserRecordingSaving' : state?.recording_pending_save ? 'browserRecordingRetrySave' : 'browserRecordingStop')}</button>
      : recordingResult ? <>
        <button type="button" className="ds-annotation-toolbar__primary" onClick={() => setRecordingPreview({ threadId, artifact: recordingResult })}><Play size={13} />{t(recordingResult.id.endsWith('.webm') ? 'browserViewVideo' : 'browserViewGif')}</button>
        <button type="button" className="ds-annotation-toolbar__btn" aria-label={t('browserRecordingFolder')} title={t('browserRecordingFolder')} onClick={() => {
          void window.dsGui.showItemInFolder(recordingResult.path).catch(e => setError(String(e)))
        }}><FolderOpen size={16} /></button>
        <button type="button" className="ds-annotation-toolbar__btn" aria-label={t('browserRecordingDismiss')} title={t('browserRecordingDismiss')} onClick={() => setSavedRecording(null)}><X size={15} /></button>
      </> : null}
  </div> : demoForced ? <BrowserDemoActivity recording={!!state?.workflow_recording} finishing={demoChanging === 'stop'} elapsed={formatClock(demoSeconds)}
    review={demoReview} failure={demoFailure} canAct={!!userControls && demoChanging === null}
    onFinish={() => void demonstrate()} onRetry={() => void demonstrate()} onToggleSteps={() => void toggleDemoSteps()}
    onAdd={() => { if (demoReview) onDemonstrationSaved?.(demoReview.message); setDemoReview(null); setNotice(t('browserDemoDrafted')) }}
    onDismiss={() => { setDemoReview(null); setDemoFailure(null) }} /> : null
  // Plain "you have the page" says nothing while no agent is involved; the bar leaves it out.
  const statusUseful = controlForced || controlDetails || capturePending
  // The bar's leading status: who has the page, the hand-over button, and anything waiting on the user.
  const controlStatus = !statusUseful ? null : <div ref={controlRoot} className={`ds-browser-status is-${controlTone}`} role="group" aria-label={t('browserControlLabel')}
    onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setControlOpen(false) }}>
    {controlDetails ? <button ref={controlButton} type="button" className="ds-browser-status-trigger" aria-expanded={controlOpen} aria-controls={controlOptionsId}
      title={t(controlHint)} onClick={() => setControlOpen(!controlOpen)}>{statusCopy}<ChevronDown size={14} aria-hidden="true" className={controlOpen ? 'is-open' : ''} /></button>
      : <span className="ds-browser-status-label" title={t(controlHint)}>{statusCopy}</span>}
    {showControlButton && state ? <button type="button" className="ds-browser-control" disabled={!visible || !fresh || pending || controlBusy}
      aria-busy={controlBusy} onClick={() => { setControlOpen(false); void control(state.owner === 'user' ? 'agent' : 'user') }}>
      {controlBusy ? <LoaderCircle className="ds-browser-control-spinner" size={14} /> : state.owner === 'user' ? <Play size={14} /> : <Hand size={14} />}
      {t(controlBusy ? 'browserControlSwitching' : requiresReview && state.owner !== 'user' ? 'browserInspectAndHandle' : state.assistance && state.owner === 'user' ? 'browserAssistContinue' : state.owner === 'user' ? 'browserReturnControl' : 'browserTakeControl')}
    </button> : null}
    {controlOpen && controlDetails ? <div id={controlOptionsId} className="ds-browser-control-details">
      <p>{t(controlHint)}</p>
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
      <span key={item.id}>{item.filename} · {item.state === 'completed' ? t('browserDownloadReady') : item.state === 'canceled' ? t('browserDownloadCanceled') : t('browserDownloadPending')}
        {item.state === 'completed' && item.path ? <button onClick={() => void window.dsGui.showItemInFolder(item.path!)}>{t('browserDownloadReady')}</button> : null}
      </span>)}</div> : null}
    {error && !hasConnectionProblem ? <p role="alert" className="ds-browser-notice">{error}</p> : null}
    {hasConnectionProblem && (!requiresReview || state?.healthy === false) ? <div className="ds-browser-notice">
      <button disabled={pending || controlBusy} onClick={() => void refreshBrowser()}>{t('browserRefreshView')}</button>
      {state?.healthy === false ? <button disabled={pending || controlBusy} onClick={() => void perform('/recover', {})}>{t('browserRecover')}</button> : null}
      <details><summary>{t('browserTechnicalDetails')}</summary><pre>{error || connectionError || state?.error}</pre></details>
    </div> : null}
    </div> : null}
  </div>
  return <div className={`ds-shared-browser${remote ? '' : ' is-native'}${state?.assistance?.status === 'human' ? ' is-human-assistance' : ''}`}>
    {visible && state && state.persistent !== false ? <BrowserCookieSync threadId={threadId} state={state?.cookie_sync} generation={state?.generation}
      agentBusy={agentWorking}
      blank={!remote && !inputHeld && !pageOpen} updateRequest={cookieUpdate}
      manage={cookieSettings} anchor={cookieAnchor} onOpen={anchor => { setCookieAnchor(anchor ?? menuButton.current?.getBoundingClientRect() ?? null); setCookieSettings(true) }} onClose={() => { setCookieSettings(false); menuButton.current?.focus() }} /> : null}
    <div className="ds-dev-browser__chrome ds-browser-chrome">
      <div className="ds-dev-browser__tabs">
        <div className="ds-dev-browser__tab-scroll" aria-label={t('browserTabs')}>
          {(tabViews.length ? tabViews : [{ id: '', title: t('browserNewTab'), url: '', active: true }]).map(tab =>
            <div className={`ds-dev-browser__tab${tab.active ? ' ds-dev-browser__tab--active' : ''}`} key={tab.id || 'placeholder'}>
              <button className="ds-dev-browser__tab-main" aria-pressed={tab.active} disabled={!tabsEnabled} title={tab.title || tab.url}
                onClick={() => { if (!tab.id) return; if (remote || isPopup(tab.id)) action({ action: 'switch_tab', tab_id: tab.id }); else activatePageTab(threadId, tab.id) }}>
                {agentTab?.tab_id === tab.id ? <LoaderCircle className="ds-browser-control-spinner" size={12} aria-label={t('browserAgentControl')} /> : <Globe2 className="ds-dev-browser__tab-icon" />}<span className="ds-dev-browser__tab-label">{!tab.url || tab.url === BLANK_PAGE ? t('browserNewTab') : tab.title || tab.url}</span>
              </button>
              {tab.id && !soleBlank ? <button className={`ds-dev-browser__tab-close${tab.active ? ' is-visible' : ''}`} aria-label={`${t('browserCloseTab')} ${tab.title}`} title={t('browserCloseTab')} disabled={remote ? !canNavigate : !canBrowse}
                onClick={() => { if (remote || isPopup(tab.id)) action({ action: 'close_tab', tab_id: tab.id }); else closePageTab(threadId, tab.id) }}><X size={11} /></button> : null}
            </div>)}
        </div>
        <button className="ds-dev-browser__icon-btn" aria-label={t('browserNewTab')} title={t('browserNewTab')} disabled={remote ? !canNavigate : !canBrowse}
          onClick={() => { if (remote) action({ action: 'new_tab' }); else openPageTab(threadId, BLANK_PAGE) }}><Plus size={14} /></button>
      </div>
      <form className="ds-dev-browser__toolbar" onSubmit={(e) => { e.preventDefault(); navigate() }}>
        <div className="ds-dev-browser__nav">
          <button type="button" className="ds-dev-browser__icon-btn" aria-label={t('browserBack')} title={t('browserBack')} disabled={remote ? !userControls : !canBrowse || !nativeHistory('canGoBack')}
            onClick={() => { if (remote) action({ action: 'back' }); else pageWebview(activeTab?.id)?.goBack() }}><ArrowLeft size={14} /></button>
          <button type="button" className="ds-dev-browser__icon-btn" aria-label={t('browserForward')} title={t('browserForward')} disabled={remote ? !userControls : !canBrowse || !nativeHistory('canGoForward')}
            onClick={() => { if (remote) action({ action: 'forward' }); else pageWebview(activeTab?.id)?.goForward() }}><ArrowRight size={14} /></button>
          {canStop ?
            <button type="button" className="ds-dev-browser__icon-btn" aria-label={t('browserStop')} title={t('browserStop')} onClick={() => void stopLoading()}><CircleStop size={13} /></button> :
            <button type="button" className="ds-dev-browser__icon-btn" aria-label={t('browserReload')} title={t('browserReload')} disabled={remote ? !userControls : !canBrowse || !pageOpen}
              onClick={() => { if (remote) action({ action: 'reload' }); else pageWebview(activeTab?.id)?.reloadIgnoringCache() }}>{loading ? <LoaderCircle className="ds-browser-control-spinner" size={13} /> : <RotateCw size={13} />}</button>}
        </div>
        <input className="ds-dev-browser__omnibox" aria-label={t('browserAddressPlaceholder')} placeholder={t('browserAddressPlaceholder')} value={url} disabled={!addressEnabled} onChange={(e) => setUrl(e.target.value)} />
        <button className="ds-dev-browser__icon-btn" aria-label={t('browserOpen')} title={t('browserOpen')} disabled={!addressEnabled || !url.trim()}><ArrowRight size={13} /></button>
        {onAttachImage ? <button ref={annotationButton} type="button" className="ds-dev-browser__icon-btn" aria-label={t(inspect ? 'browserExitSelection' : 'browserAnnotate')} title={t(inspect ? 'browserExitSelection' : 'browserAnnotate')} aria-pressed={annotationBarVisible} disabled={!annotationSurface || agentHolds}
          onClick={() => { if (!annotationBarVisible) setAnnotationBarShown(true); else if (annotationReady && canInspect) annotation.current?.togglePick() }}><BrowserPointerIcon /></button>
          : canInspect ? <button type="button" className="ds-dev-browser__icon-btn" aria-label={t('browserInspect')} title={t('browserInspectHint')} aria-pressed={inspect} disabled={remote ? !userControls : !canBrowse} onClick={() => setInspect(!inspect)}><BrowserPointerIcon /></button> : null}
        <div className="ds-browser-menu-anchor" ref={menuRoot}>
          <button ref={menuButton} type="button" className="ds-dev-browser__icon-btn" aria-label={t('browserMore')} title={t('browserMore')} aria-haspopup="menu" aria-expanded={more} onClick={() => setMore(!more)}><MoreHorizontal size={16} /></button>
          {more ? <div className="ds-dock-menu" role="menu" aria-label={t('browserMore')}
            onClick={(e) => { if ((e.target as Element).closest('button:not([aria-expanded])')) setMore(false) }}
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
            {/* Grouped by what the user wants to do; recording formats sit behind one entry. */}
            {state?.video_recording ? <button type="button" role="menuitem" className="ds-dock-menu-item" disabled={!userControls} onClick={() => void stopRecording()}><Video size={15} />{t('browserVideoStop')}</button> : null}
            {state?.recording_pending_save ? <button type="button" role="menuitem" className="ds-dock-menu-item" disabled={!userControls} onClick={() => void stopRecording()}><Film size={15} />{t('browserRecordingRetrySave')}</button> : null}
            {state?.recording ? <button type="button" role="menuitem" className="ds-dock-menu-item" disabled={!userControls} onClick={() => void stopRecording()}><Film size={15} />{t('browserFinishRecording')}</button> : null}
            {latestRecording ? <button type="button" role="menuitem" className="ds-dock-menu-item" onClick={() => {
              setSavedRecording({ threadId, artifact: latestRecording }); setRecordingPreview({ threadId, artifact: latestRecording })
            }}><Play size={15} />{t(latestRecording.id.endsWith('.webm') ? 'browserViewVideo' : 'browserViewGif')}</button> : null}
            {screenRecording ? null : menuDetailItem('record', <Clapperboard size={15} />, t('browserRecordScreen'), t(demoBusy ? 'browserRecordBusyDemo' : 'browserRecordScreenDetail'),
              { disabled: !userControls || demoBusy, 'aria-expanded': recordChoice, onClick: () => setRecordChoice(!recordChoice) },
              recordChoice ? <ChevronDown size={14} className="ds-browser-menu-chevron" /> : <ChevronRight size={14} className="ds-browser-menu-chevron" />)}
            {recordChoice && !screenRecording ? <div className="ds-browser-menu-choices">
              {menuDetailItem('video', <Video size={15} />, t('browserRecordVideo'), t(videoUnavailable ? 'browserVideoUnavailable' : 'browserRecordVideoDetail'),
                { disabled: !userControls || videoUnavailable, onClick: () => action({ action: 'video_start' }) })}
              {videoUnavailable ? <button type="button" role="menuitem" className="ds-dock-menu-item" onClick={() => {
                void copyText(FFMPEG_INSTALL_COMMAND).then(copied => { if (copied) setNotice(t('browserFfmpegCommandCopied')) })
              }}><Copy size={15} />{t('browserCopyFfmpegCommand')}</button> : null}
              {menuDetailItem('gif', <Film size={15} />, t('browserRecordGif'), t('browserRecordGifDetail'),
                { disabled: !userControls, onClick: () => action({ action: 'record_start' }) })}
            </div> : null}
            <div className="ds-browser-menu-divider" role="separator" />
            {filePath && isHtmlPreviewPath(filePath) && onOpenFileInEditor ? <button type="button" role="menuitem" className="ds-dock-menu-item" onClick={() => onOpenFileInEditor(filePath)}><FileCode2 size={15} />{t('browserEditSource')}</button> : null}
            <button type="button" role="menuitem" className="ds-dock-menu-item" disabled={remote ? !userControls : !pageOpen} onClick={() => void openDevTools()}><Bug size={15} />{t('browserDevTools')}</button>
            {onAttachImage && !annotationBarShown ? <button type="button" role="menuitem" className="ds-dock-menu-item" disabled={!annotationSurface || agentHolds} onClick={() => setAnnotationBarShown(true)}><Pencil size={15} />{t('browserShowAnnotationTools')}</button> : null}
            <button type="button" role="menuitem" className="ds-dock-menu-item" disabled={!pageUrl || !normalizeBrowseUrlInput(pageUrl)} onClick={() => { if (pageUrl) void window.dsGui.openExternal(pageUrl).catch(e => setError(String(e))) }}><ExternalLink size={15} />{t('browserOpenExternal')}</button>
            {(state && state.persistent !== false) || remote || state?.task_running ? <div className="ds-browser-menu-divider" role="separator" /> : null}
            {state && state.persistent !== false ? <>
              <button type="button" role="menuitem" className="ds-dock-menu-item" aria-haspopup="dialog" onClick={event => { setCookieAnchor(menuButton.current?.getBoundingClientRect() ?? event.currentTarget.getBoundingClientRect()); setCookieSettings(true) }}><Globe2 size={15} />{t('browserCookieManage')}</button>
              <button type="button" role="menuitem" className="ds-dock-menu-item" onClick={() => setCookieUpdate(count => count + 1)}><RotateCw size={15} />{t('browserCookieUpdate')}</button>
            </> : null}
            {/* Workbench tabs stay open; ending only matters for a task or a private browser. */}
            {remote || state?.task_running ? <button type="button" role="menuitem" className="ds-dock-menu-item" disabled={!state?.active || pending} onClick={() => void control('stopped')}><Square size={15} />{t(state?.task_running ? 'browserEndTaskAndSession' : 'browserEndSession')}</button> : null}
          </div> : null}
        </div>
      </form>
      {detectedUrls.length ? <div className="ds-dev-browser__chips">{detectedUrls.map(target => <button key={target} className="ds-dev-browser__chip" disabled={pending || !fresh} title={target} onClick={() => void openPreview(target)}>{formatDevPreviewUrlLabel(target)}</button>)}</div> : null}
    </div>
    {agentTab ? <div className="ds-browser-notice" role="status"><span>{t('browserAgentTarget', { name: agentTab.title || agentTab.url })}</span></div> : null}
    {remote && image && (!fresh || !state?.active || state?.healthy === false) ? <div className="ds-browser-notice" role="status">{t('browserStaleFrame')}</div> : null}
    {state?.video_error || state?.recording_error ? <div className="ds-browser-notice" role="alert"><span>{t('browserRecordingFailed', { error: state.video_error || state.recording_error })}</span>
      {state?.recording_pending_save ? <button type="button" disabled={!userControls} onClick={() => void stopRecording()}>{t('browserRecordingRetrySave')}</button> : null}</div> : null}
    <div className={`ds-browser-content${annotationBarVisible || statusBarOnly ? ' has-annotation-bar' : ''}`} ref={pageArea}>
    {annotationSurface && onAttachImage ? <BrowserAnnotation key={`${inspectedPage}:${state?.generation}:${state?.owner}`} ref={annotation}
      collapsed={!annotationBarVisible} disabled={!annotationReady} pickEnabled={canInspect} picking={inspect} onPickingChange={setInspect} capture={captureForAnnotation} pageUrl={pageUrl}
      onAdd={async (file, annotated, capturedPageUrl) => {
        const attached = await onAttachImage(file, path => annotationContextNote(path, annotated, capturedPageUrl))
        if (attached) setNotice(t('annotationAdded'))
        return attached
      }}
      onHide={() => { setAnnotationBarShown(false); setInspect(false) }} onError={setError} status={controlStatus} activity={activityCard} closable={!controlForced && !activityForced}
      tools={conversationId && state ? <button type="button" className={`ds-annotation-toolbar__btn${state.workflow_recording ? ' is-recording' : ''}`}
        aria-label={t(state.workflow_recording ? 'browserDemoFinish' : 'browserDemoStart')} aria-pressed={!!state.workflow_recording}
        title={state.workflow_recording ? t('browserDemoFinish') : recordingBusy ? t('browserDemoBusyRecording') : `${t('browserDemoStart')}：${t('browserDemoDetail')}`}
        disabled={!userControls || demoChanging !== null || (recordingBusy && !state.workflow_recording)} onClick={() => void demonstrate()}><GraduationCap size={16} /></button> : null} /> : null}
    {statusBarOnly ? <div className="ds-annotation"><div className="ds-annotation-toolbar" role="toolbar" aria-label={t('browserControlLabel')} data-state="rest">{activityCard}{controlStatus}</div></div> : null}
    {recordingPreview?.threadId === threadId ? <BrowserRecordingPreview key={recordingPreview.artifact.id} threadId={threadId} recording={recordingPreview.artifact} onClose={() => setRecordingPreview(null)} /> : null}
    {pickHint || notice ? <div className="ds-browser-feedback" role="status"><span>{pickHint ? t('browserPickInstruction') : notice}</span>{!pickHint && savedNotice?.notice === notice ? <button onClick={() => {
        void window.dsGui.showItemInFolder(savedNotice.path).catch(e => setError(String(e)))
      }}>{t('threadMenuRevealInFolder')}</button> : null}<button aria-label={t('browserDismissPreview')} onClick={() => { setInspect(false); setNotice('') }}><X size={13} /></button></div> : null}
    {!pickHint && !notice && !remote && activeTab && activeTab.error !== null ? <div className="ds-browser-feedback" role="status"><span>{activeTab.error || t('browserLoadFailed')}</span></div> : null}
    {!pickHint && !notice && captureError ? <div className="ds-browser-feedback" role="alert"><span>{t('browserDemoTabUnavailable', { error: captureError })}</span></div> : null}

      {remote && image ? <BrowserViewport image={image} enabled={!!userControls && frameFresh && !controlOpen && !more && !state.dialog} reviewOnly={!!unresolvedReceipt} resizeEnabled={!!userControls && frameFresh && !controlOpen && !more && !state.video_recording} generation={state.generation ?? 0}
        sceneId={state.scene?.scene_id} inspect={inspect && canInspect} onInspectCancel={() => setInspect(false)} width={state.viewport?.width ?? 1200} height={state.viewport?.height ?? 760} label={t('browserLiveView')}
        send={async (body) => {
          if (body.kind === 'pick') {
            const result = await browserRequest<{ pick?: unknown; url?: string }>(threadId, '/input', body)
            const parsed = parsePreviewPickConsoleMessage(PREVIEW_PICK_CONSOLE_PREFIX + JSON.stringify({ type: 'pick', payload: result.pick }))
            if (alive.current && parsed?.type === 'pick' && pickSource && result.url?.split('#')[0] === state.url?.split('#')[0]) {
              onPreviewPick?.({ ...parsed.payload, ...pickSource }); setNotice(t('browserPickAdded'))
              if (onAttachImage) setInspect(false)
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
                  apply(await browserRequest<BrowserState>(threadId, viewSuffix))
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
            try { apply(await browserRequest<BrowserState>(threadId, viewSuffix)) }
            catch (e) { if (alive.current) { setFresh(false); setFrameFresh(false); setConnectionError(e instanceof Error ? e.message : String(e)) } }
            return result
          } finally { if (alive.current) setPending(false) }
        }} onError={setError} /> :
        remote ? <div className="ds-browser-empty"><Globe2 size={28} strokeWidth={1.3} /><h3>{t(pending ? 'browserStarting' : 'browserStartTitle')}</h3><p>{t('browserStartHint')}</p></div>
        // The agent's page stays visible underneath while it works; the user's input waits.
        : inputHeld ? <div className="ds-browser-shield" aria-hidden="true" />
        : !pageOpen ? <div className="ds-browser-empty"><Globe2 size={28} strokeWidth={1.3} /><h3>{t('browserStartTitle')}</h3><p>{t('browserStartHint')}</p>
          <button type="button" className="ds-browser-empty-action" disabled={!canBrowse} onClick={() => { if (activeTab) loadInTab(activeTab.id, DEFAULT_DEV_PREVIEW_URL) }}>{t('browserOpenDefault')}</button></div>
        : null}

    </div>
  </div>
}
