import { useCallback, useEffect, useMemo, useRef, useState, type ReactElement } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import { AppWindow, ArrowUpRight, CheckCircle2, ChevronDown, CircleAlert, Eye, Monitor, X } from 'lucide-react'
import { create } from 'zustand'
import {
  dismissEndedCuaPreview,
  restoreCuaPreview,
  markCuaPreviewLive,
  useCuaPreviewStore,
  type CuaPreviewSession
} from '../../store/cua-preview-store'
import { claimScreenPermissionPrompt } from './screen-permission-prompt'
import { CuaPermissionsDialog } from './CuaPermissionsDialog'
import { CuaControlBar } from './CuaControlBar'
import { useCuaStillFrame } from './use-cua-still-frame'
import { useCuaWindowStream } from './use-cua-window-stream'

/** One anchored card: expand on the first frame and settle back after completion. */

const MIN_DOCK_WIDTH = 200
const FALLBACK_ASPECT = 16 / 10

const useRailSlot = create<{ slot: HTMLElement | null }>(() => ({ slot: null }))

/** Docking place under the operation panel; the card portals here when it fits. */
export function CuaPreviewRailSlot(): ReactElement {
  const ref = useCallback((element: HTMLDivElement | null) => {
    useRailSlot.setState({ slot: element })
  }, [])
  return <div ref={ref} className="ds-cua-preview-slot mt-3 flex justify-center empty:mt-0" />
}

function useSlotWidth(slot: HTMLElement | null): number {
  const [width, setWidth] = useState(0)
  useEffect(() => {
    if (!slot) {
      setWidth(0)
      return
    }
    const update = (): void => setWidth(slot.offsetParent !== null ? slot.clientWidth : 0)
    update()
    const observer = new ResizeObserver(update)
    observer.observe(slot)
    return () => observer.disconnect()
  }, [slot])
  return width
}

export function CuaPreview({ threadId }: { threadId: string | null }): ReactElement | null {
  const { t } = useTranslation('common')
  const session = useCuaPreviewStore((state) => (threadId ? state.sessions[threadId] : undefined))
  const slot = useRailSlot((state) => state.slot)
  const slotWidth = useSlotWidth(slot)
  const slotUsable = slotWidth > 0
  const compactRail = slotUsable && slotWidth < MIN_DOCK_WIDTH
  const [peekFor, setPeekFor] = useState<string | null>(null)
  const cardRef = useRef<HTMLElement>(null)
  const [anchor, setAnchor] = useState({ left: 0, top: 0, width: 320 })
  const [expandedFor, setExpandedFor] = useState<string | null>(null)
  const permissionKey = `${threadId}:${session?.turnId}`
  const [collapsedFor, setCollapsedFor] = useState<string | null>(null)
  const [autoOpenedFor, setAutoOpenedFor] = useState<string | null>(null)
  const contentRef = useRef<HTMLDivElement>(null)
  const [height, setHeight] = useState<number>()
  const [animate, setAnimate] = useState(true)
  useEffect(() => {
    const element = contentRef.current
    if (!element) return
    const measure = (): void => {
      // CSS height uses layout pixels; viewport bounds already include body zoom.
      const next = element.offsetHeight
      if (next > 0) setHeight(next + 2)
    }
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(element)
    return () => observer.disconnect()
  }, [threadId, !!session, slotUsable, compactRail, slot])
  const collapse = useCallback(() => {
    setCollapsedFor(permissionKey)
    setExpandedFor(null)
    setPeekFor(null)
  }, [permissionKey])
  const onFrameReady = useCallback(() => {
    if (collapsedFor !== permissionKey && autoOpenedFor !== permissionKey) {
      setAnimate(true)
      setAutoOpenedFor(permissionKey)
      setExpandedFor(permissionKey)
      setPeekFor(permissionKey)
    }
  }, [collapsedFor, autoOpenedFor, permissionKey])
  const peeking = compactRail && peekFor === permissionKey
  const expanded = compactRail ? peeking : expandedFor === permissionKey
  useEffect(() => {
    if (!compactRail || !slot) return
    const position = (): void => {
      const rect = slot.getBoundingClientRect()
      // Fixed CSS coordinates use unzoomed layout pixels, just like card height.
      const zoom = Number.parseFloat(getComputedStyle(document.body).zoom) || 1
      const width = Math.min(320, Math.max(120, rect.left / zoom - 16))
      const top = Math.max(8, Math.min(rect.top / zoom, window.innerHeight / zoom - (cardRef.current?.offsetHeight ?? 300) - 8))
      setAnchor({ left: Math.max(8, rect.left / zoom - width - 8), top, width })
    }
    position()
    const outside = (event: PointerEvent): void => {
      if (event.target instanceof Node && !slot.contains(event.target) && !cardRef.current?.contains(event.target) && peeking) collapse()
    }
    window.addEventListener('resize', position)
    window.addEventListener('scroll', position, true)
    document.addEventListener('pointerdown', outside)
    return () => {
      window.removeEventListener('resize', position)
      window.removeEventListener('scroll', position, true)
      document.removeEventListener('pointerdown', outside)
    }
  }, [compactRail, slot, peeking, height, collapse])
  const [permissionFor, setPermissionFor] = useState<string | null>(null)
  // An ended card may close once nothing on it still needs the user's review.
  const [reviewPending, setReviewPending] = useState(true)
  useEffect(() => {
    if (session?.phase !== 'ended' || reviewPending) return
    const timer = window.setTimeout(() => { setAnimate(true); collapse() }, 1400)
    return () => window.clearTimeout(timer)
  }, [session?.phase, permissionKey, reviewPending, collapse])
  useEffect(() => {
    if (!expanded) return
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key === 'Escape' && permissionFor !== permissionKey) { setAnimate(false); collapse() }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [expanded, permissionFor, permissionKey, collapse])
  const requestPermission = useCallback(() => {
    setPermissionFor(`${threadId}:${session?.turnId}`)
  }, [threadId, session?.turnId])
  useEffect(() => {
    if (!threadId || typeof window.dsGui?.runtimeRequest !== 'function') return
    let cancelled = false
    void window.dsGui.runtimeRequest(`/v1/threads/${encodeURIComponent(threadId)}/cua`, 'GET')
      .then(response => {
        if (!cancelled && response.ok) restoreCuaPreview(threadId, JSON.parse(response.body))
      }).catch(() => { /* Live tool events can still arm the preview. */ })
    return () => { cancelled = true }
  }, [threadId])
  if (!threadId || !session) return null
  const card = <section ref={cardRef} hidden={compactRail && !peeking} aria-label={t('cuaPreviewRegion')} data-cua-preview={threadId}
    style={{ height, ...(compactRail ? anchor : {}) }}
    className={`overflow-hidden ${animate ? 'transition-[height] duration-200' : ''} ease-[cubic-bezier(0.23,1,0.32,1)] motion-reduce:transition-none rounded-xl border border-ds-border bg-white dark:bg-ds-card text-ds-ink shadow-panel ${
      compactRail ? 'fixed z-50' : slotUsable ? 'relative w-full' : 'relative w-full max-w-80'
    }`}>
    <div ref={contentRef} className="max-h-[calc(100vh-7rem)] overflow-y-auto">
    <CuaPreviewSessionView key={`${threadId}:${session.turnId ?? ''}:${session.surface ?? ''}:${session.appId ?? ''}`}
      threadId={threadId} session={session} expanded={expanded}
      autoPreview={collapsedFor !== permissionKey} onFrameReady={onFrameReady} reviewPending={reviewPending}
      onExpand={() => { setAnimate(true); setExpandedFor(permissionKey) }} onCollapse={() => { setAnimate(true); collapse() }}
      onPermissionRequired={requestPermission} onOpenPermissions={() => setPermissionFor(permissionKey)}
      onDismiss={session.phase === 'ended' && !reviewPending ? () => dismissEndedCuaPreview(threadId) : undefined} />
    <CuaControlBar key={threadId} threadId={threadId} compact onReviewPending={setReviewPending} />
    </div>
  </section>
  // The fallback belongs to the conversation layout, never to the whole window.
  // A fullscreen sidebar hides it with the conversation instead of being covered.
  return <>
    {compactRail && slot ? <>
      {createPortal(<button type="button" className="ds-operation-dock-rail__btn relative"
        aria-label={t('cuaPreviewShow')} title={t('cuaPreviewShow')} aria-expanded={peeking}
        onClick={() => { setAnimate(true); peeking ? collapse() : setPeekFor(permissionKey) }}>
        <Monitor className="h-4 w-4" aria-hidden />
        {(session.phase !== 'ended' || reviewPending) && <span aria-hidden
          className={`absolute right-0.5 top-0.5 h-1.5 w-1.5 rounded-full ${reviewPending ? 'bg-amber-500' : 'bg-emerald-500'}`} />}
      </button>, slot)}
      {createPortal(card, document.body)}
    </> : slotUsable && slot ? createPortal(card, slot) : <div
      className="ds-no-drag mx-3 mb-3 flex max-h-[45vh] min-w-0 shrink-0 justify-end overflow-y-auto"
      data-cua-conversation-preview>{card}</div>}
    {permissionFor === permissionKey && <CuaPermissionsDialog onClose={() => setPermissionFor(null)} />}
  </>
}

function CuaPreviewSessionView({ threadId, session, expanded, onExpand, onCollapse, onPermissionRequired, onOpenPermissions, onDismiss, autoPreview, onFrameReady, reviewPending }: {
  autoPreview: boolean; onFrameReady: () => void; reviewPending: boolean
  expanded: boolean; onExpand: () => void; onCollapse: () => void; onDismiss?: () => void
  threadId: string; session: CuaPreviewSession; onPermissionRequired: () => void; onOpenPermissions: () => void
}): ReactElement | null {
  const { t } = useTranslation('common')
  const [openingApp, setOpeningApp] = useState(false)
  const [openAppFailed, setOpenAppFailed] = useState(false)
  const openApp = async (): Promise<void> => {
    if (!session.appId || openingApp) return
    setOpeningApp(true)
    setOpenAppFailed(false)
    try {
      // Raising the app can close menus or open a window: the assistant observes again first.
      await window.dsGui.runtimeRequest(`/v1/threads/${encodeURIComponent(threadId)}/cua/raised`, 'POST')
        .catch(() => undefined)
      setOpenAppFailed(!await window.dsGui.openCuaApp(session.appId))
    } catch {
      setOpenAppFailed(true)
    } finally {
      setOpeningApp(false)
    }
  }
  // Keep the same canvas when expanding or collapsing the viewer.
  const canvas = useMemo(() => {
    const element = document.createElement('canvas')
    element.className = 'absolute inset-0 h-full w-full object-contain'
    element.setAttribute('aria-hidden', 'true')
    return element
  }, [])
  const canvasRef = useMemo(() => ({ current: canvas }), [canvas])
  const { phase } = session
  // Read once per task: turning the preview off applies from the next task. Nothing is
  // captured or fetched until the setting is known to allow it.
  const [allowed, setAllowed] = useState<boolean | null>(null)
  useEffect(() => {
    let cancelled = false
    window.dsGui.getSettings().then(
      (settings) => { if (!cancelled) setAllowed(settings.cuaWindowPreview !== false) },
      () => { if (!cancelled) setAllowed(false) }
    )
    return () => { cancelled = true }
  }, [])
  const shown = allowed === true
  const streaming = (expanded || autoPreview) && allowed === true && (phase === 'armed' || phase === 'live')

  useEffect(() => {
    if (phase === 'armed') markCuaPreviewLive(threadId)
  }, [phase, threadId])

  const live = useCuaWindowStream({
    canvasRef,
    appId: session.surface === 'app' ? session.appId : null,
    revision: session.revision,
    enabled: streaming
  })
  // Stop capture after a manual collapse; retain the latest frame.
  const useStill = shown && !live.hasFrame
  const still = useCuaStillFrame({
    canvasRef, still: session.still, enabled: useStill
  })

  const hasFrame = live.hasFrame || still.status === 'ready'
  useEffect(() => {
    if (shown && hasFrame && (phase === 'armed' || phase === 'live')) onFrameReady()
  }, [shown, hasFrame, phase, onFrameReady])
  useEffect(() => {
    canvas.style.visibility = shown && hasFrame ? 'visible' : 'hidden'
  }, [canvas, shown, hasFrame])
  const frameSize = useStill && still.status === 'ready' ? still.frameSize : live.frameSize ?? still.frameSize

  // Capture problems are explained only inside the viewer.
  const problem = live.status === 'permission' || live.status === 'failed' || live.status === 'no-window' || live.status === 'ambiguous' ? live.status : null
  useEffect(() => {
    if (!expanded || !shown || session.surface !== 'app' || phase === 'ended' || window.dsGui.platform !== 'darwin' || typeof window.dsGui.getCuaScreenPermission !== 'function') return
    let cancelled = false
    const check = async (returning = false): Promise<void> => {
      try {
        const permission = await window.dsGui.getCuaScreenPermission()
        if (cancelled) return
        if (claimScreenPermissionPrompt(permission)) onPermissionRequired()
        if (permission.status === 'granted' && (returning || problem === 'permission')) {
          window.dispatchEvent(new Event('cua-permission-recheck'))
        }
      } catch { /* Keep the inline entry available when detection fails. */ }
    }
    void check()
    const onFocus = (): void => { void check(true) }
    window.addEventListener('focus', onFocus)
    return () => { cancelled = true; window.removeEventListener('focus', onFocus) }
  }, [expanded, shown, phase, problem, threadId, session.turnId, session.surface, onPermissionRequired])
  const appName = live.appName ?? t(session.surface === 'browser' ? 'cuaPreviewBrowser' : 'cuaPreviewComputer')
  const status = phase === 'ended'
    ? t(reviewPending ? 'cuaControlUnknown' : session.outcome === 'stopped' ? 'cuaPreviewStopped' : session.outcome === 'failed' ? 'cuaPreviewIncomplete' : session.outcome === 'completed' ? 'cuaPreviewDone' : 'cuaPreviewEnded')
    : t('cuaPreviewWorking', { app: appName })
  const attachCanvas = (element: HTMLDivElement | null): void => {
    if (element && canvas.parentElement !== element) element.prepend(canvas)
  }
  const outcomeIcon = phase === 'ended' && !reviewPending
    ? session.outcome === 'completed' ? <CheckCircle2 className="h-5 w-5 shrink-0 text-emerald-600" aria-hidden />
      : session.outcome === 'failed' ? <CircleAlert className="h-5 w-5 shrink-0 text-amber-600" aria-hidden /> : null
    : null
  const placeholder = <Monitor className="h-5 w-5 text-ds-muted" aria-hidden />

  return <>
    {expanded ? <div className="flex items-center gap-2 px-3 py-2 text-xs">
      {session.surface === 'app' && session.appId && window.dsGui.platform === 'darwin' && <button
        type="button" onClick={() => void openApp()} disabled={openingApp}
        aria-label={t('cuaPreviewOpenApp')} title={t('cuaPreviewOpenApp')}
        className="grid h-7 w-7 shrink-0 place-items-center rounded-md text-ds-muted hover:bg-ds-hover disabled:opacity-40 focus-visible:outline focus-visible:outline-2">
        <span className="relative h-4 w-4" aria-hidden>
          <AppWindow className="h-4 w-4" strokeWidth={1.75} />
          <ArrowUpRight className="absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-sm bg-white dark:bg-ds-card" strokeWidth={1.75} />
        </span>
      </button>}
      <div className="min-w-0 flex-1">
        {openAppFailed && <span role="status" aria-label={t('cuaPreviewOpenAppFailed')}
          title={t('cuaPreviewOpenAppFailed')} className="flex min-w-0 items-center gap-1 text-ds-muted">
          <CircleAlert className="h-3.5 w-3.5 shrink-0" aria-hidden />
          <span className="truncate">{t('cuaPreviewOpenAppFailedShort')}</span>
        </span>}
      </div>
      {hasFrame && <span className="shrink-0 text-ds-muted">{live.hasFrame && streaming && live.status === 'ok'
        ? t('cuaPreviewLive') : t('cuaPreviewLastFrame')}</span>}
      <button type="button" onClick={onCollapse} aria-label={t('cuaPreviewCollapse')} title={t('cuaPreviewCollapse')}
        className="grid h-7 w-7 shrink-0 place-items-center rounded-md text-ds-muted hover:bg-ds-hover focus-visible:outline focus-visible:outline-2">
        <ChevronDown className="h-4 w-4" aria-hidden />
      </button>
    </div> : null}
    {expanded ? <>
      {shown && hasFrame && <div ref={attachCanvas} className="relative w-full bg-ds-subtle"
        style={{ aspectRatio: frameSize ? `${frameSize.width} / ${frameSize.height}` : `${FALLBACK_ASPECT}` }} />}
      {(!shown || !hasFrame || problem) && <div role="status" className="space-y-2 bg-ds-subtle px-3 py-4 text-xs text-ds-muted">
        <p>{allowed === false ? t('cuaPreviewDisabled')
          : problem === 'permission' ? t('cuaPreviewPermission')
            : problem === 'ambiguous' ? t('cuaPreviewAmbiguous')
            : problem === 'no-window' ? t('cuaPreviewNoWindow')
              : problem === 'failed' || still.status === 'error' ? t('cuaPreviewFailed')
                : phase === 'ended' ? t('cuaPreviewNoRecordedFrame')
                  : live.status === 'unsupported' ? t('cuaPreviewUnsupported') : t('cuaPreviewWaitingFrame')}</p>
        {problem === 'permission' && shown && <button type="button" onClick={onOpenPermissions}
          className="rounded-md border border-ds-border px-2.5 py-1 text-ds-ink hover:bg-ds-hover">{t('cuaPreviewOpenSettings')}</button>}
      </div>}
      {phase === 'ended' && <p role="status" className="flex items-center gap-2 px-3 py-2 text-xs text-ds-muted">{outcomeIcon}{status}</p>}
    </> : <div className="flex items-center">
      <button type="button" onClick={onExpand} aria-label={`${t('cuaPreviewShow')}: ${status}`} title={t('cuaPreviewShow')} aria-expanded={false}
        className="flex min-w-0 flex-1 items-center gap-3 p-3 text-left hover:bg-ds-hover focus-visible:outline focus-visible:outline-2">
        <div ref={attachCanvas} className="relative grid h-12 w-20 shrink-0 place-items-center overflow-hidden rounded-md bg-ds-subtle">
          {!shown || !hasFrame ? placeholder : null}
        </div>
        {outcomeIcon}
        <span title={phase === 'ended' ? status : session.label ?? status} className="min-w-0 truncate text-xs leading-relaxed">{status}</span>
        <Eye className="ml-auto h-4 w-4 shrink-0 text-ds-muted" aria-hidden />
      </button>
      {onDismiss ? <button type="button" onClick={onDismiss} aria-label={t('cuaPreviewDismiss')} title={t('cuaPreviewDismiss')}
        className="mr-2 grid h-7 w-7 shrink-0 place-items-center rounded-md text-ds-muted hover:bg-ds-hover focus-visible:outline focus-visible:outline-2">
        <X className="h-4 w-4" aria-hidden />
      </button> : null}
    </div>}
  </>
}
