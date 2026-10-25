import { useCallback, useEffect, useMemo, useState, type ReactElement } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import { Monitor, X } from 'lucide-react'
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

/** A compact activity entry with an opt-in viewer. Controls stay mounted when
 * the viewer closes or its capture target changes. */

const MIN_DOCK_WIDTH = 200
const FALLBACK_ASPECT = 16 / 10

const useRailSlot = create<{ slot: HTMLElement | null }>(() => ({ slot: null }))

/** Docking place under the operation panel; the card portals here when it fits. */
export function CuaPreviewRailSlot(): ReactElement {
  const ref = useCallback((element: HTMLDivElement | null) => {
    useRailSlot.setState({ slot: element })
  }, [])
  return <div ref={ref} className="ds-cua-preview-slot mt-3 empty:mt-0" />
}

function useSlotUsable(slot: HTMLElement | null): boolean {
  const [usable, setUsable] = useState(false)
  useEffect(() => {
    if (!slot) {
      setUsable(false)
      return
    }
    const update = (): void => setUsable(slot.offsetParent !== null && slot.clientWidth >= MIN_DOCK_WIDTH)
    update()
    const observer = new ResizeObserver(update)
    observer.observe(slot)
    return () => observer.disconnect()
  }, [slot])
  return usable
}

export function CuaPreview({ threadId }: { threadId: string | null }): ReactElement | null {
  const { t } = useTranslation('common')
  const session = useCuaPreviewStore((state) => (threadId ? state.sessions[threadId] : undefined))
  const slot = useRailSlot((state) => state.slot)
  const slotUsable = useSlotUsable(slot)
  const [expandedFor, setExpandedFor] = useState<string | null>(null)
  const permissionKey = `${threadId}:${session?.turnId}`
  const expanded = expandedFor === permissionKey
  const [permissionFor, setPermissionFor] = useState<string | null>(null)
  // An ended card may close once nothing on it still needs the user's review.
  const [reviewPending, setReviewPending] = useState(true)
  useEffect(() => {
    if (!expanded) return
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key === 'Escape' && permissionFor !== permissionKey) setExpandedFor(null)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [expanded, permissionFor, permissionKey])
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
  const card = <section aria-label={t('cuaPreviewRegion')} data-cua-preview={threadId}
    className={`overflow-hidden rounded-xl border border-ds-border bg-white dark:bg-ds-card text-ds-ink shadow-panel ${
      expanded ? 'fixed bottom-24 right-5 z-50 w-[640px] max-w-[calc(100vw-2rem)] max-h-[calc(100vh-7rem)] overflow-y-auto'
        : slotUsable ? 'relative w-full' : 'fixed bottom-24 right-5 z-50 w-80 max-w-[calc(100vw-2rem)]'
    }`}>
    <CuaPreviewSessionView key={`${threadId}:${session.turnId ?? ''}:${session.surface ?? ''}:${session.appId ?? ''}`}
      threadId={threadId} session={session} expanded={expanded}
      onExpand={() => setExpandedFor(permissionKey)} onCollapse={() => setExpandedFor(null)}
      onPermissionRequired={requestPermission} onOpenPermissions={() => setPermissionFor(permissionKey)}
      onDismiss={session.phase === 'ended' && !reviewPending ? () => dismissEndedCuaPreview(threadId) : undefined} />
    <CuaControlBar key={threadId} threadId={threadId} compact onReviewPending={setReviewPending} />
  </section>
  // Keep the portal destination stable: expanding must not remount the controls.
  return <>
    {createPortal(card, slotUsable && slot ? slot : document.body)}
    {permissionFor === permissionKey && <CuaPermissionsDialog onClose={() => setPermissionFor(null)} />}
  </>
}

function CuaPreviewSessionView({ threadId, session, expanded, onExpand, onCollapse, onPermissionRequired, onOpenPermissions, onDismiss }: {
  expanded: boolean; onExpand: () => void; onCollapse: () => void; onDismiss?: () => void
  threadId: string; session: CuaPreviewSession; onPermissionRequired: () => void; onOpenPermissions: () => void
}): ReactElement | null {
  const { t } = useTranslation('common')
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
  const streaming = expanded && allowed === true && (phase === 'armed' || phase === 'live')

  useEffect(() => {
    if (phase === 'armed') markCuaPreviewLive(threadId)
  }, [phase, threadId])

  const live = useCuaWindowStream({
    canvasRef,
    appId: session.surface === 'app' ? session.appId : null,
    revision: session.revision,
    enabled: streaming
  })
  // A collapsed entry follows task screenshots without running screen capture.
  const useStill = shown && (!live.hasFrame || (!expanded && phase !== 'ended'))
  const still = useCuaStillFrame({
    canvasRef, still: session.still, enabled: useStill
  })

  const hasFrame = live.hasFrame || still.status === 'ready'
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
    ? t(session.outcome === 'stopped' ? 'cuaPreviewStopped' : session.outcome === 'failed' ? 'cuaPreviewIncomplete' : 'cuaPreviewEnded')
    : session.label ?? t('cuaPreviewWorking', { app: appName })
  const attachCanvas = (element: HTMLDivElement | null): void => {
    if (element && canvas.parentElement !== element) element.prepend(canvas)
  }
  const placeholder = <Monitor className="h-5 w-5 text-ds-muted" aria-hidden />

  return <>
    {expanded ? <div className="flex items-center gap-2 px-3 py-2 text-xs">
      <span className="min-w-0 flex-1 truncate">{appName}</span>
      {hasFrame && <span className="text-ds-muted">{live.hasFrame && streaming && live.status === 'ok'
        ? t('cuaPreviewLive') : t('cuaPreviewLastFrame')}</span>}
      <button type="button" onClick={onCollapse} aria-label={t('cuaPreviewCollapse')} title={t('cuaPreviewCollapse')}
        className="grid h-7 w-7 place-items-center rounded-md text-ds-muted hover:bg-ds-hover focus-visible:outline focus-visible:outline-2">
        <X className="h-4 w-4" aria-hidden />
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
      <p className="px-3 py-2 text-xs text-ds-ink">{status}</p>
    </> : <div className="flex items-center">
      <button type="button" onClick={onExpand} aria-label={`${t('cuaPreviewShow')}: ${status}`} aria-expanded={false}
        className="flex min-w-0 flex-1 items-center gap-3 p-3 text-left hover:bg-ds-hover focus-visible:outline focus-visible:outline-2">
        <div ref={attachCanvas} className="relative grid h-12 w-20 shrink-0 place-items-center overflow-hidden rounded-md bg-ds-subtle">
          {!shown || !hasFrame ? placeholder : null}
        </div>
        <span className="min-w-0 text-xs leading-relaxed line-clamp-2">{status}</span>
      </button>
      {onDismiss ? <button type="button" onClick={onDismiss} aria-label={t('cuaPreviewDismiss')} title={t('cuaPreviewDismiss')}
        className="mr-2 grid h-7 w-7 shrink-0 place-items-center rounded-md text-ds-muted hover:bg-ds-hover focus-visible:outline focus-visible:outline-2">
        <X className="h-4 w-4" aria-hidden />
      </button> : null}
    </div>}
  </>
}
