import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent, type ReactElement } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import { Check, Maximize2, Minimize2, Monitor, X } from 'lucide-react'
import { create } from 'zustand'
import {
  dismissEndedCuaPreview,
  hideCuaPreviewForTask,
  markCuaPreviewLive,
  setCuaPreviewFloating,
  useCuaPreviewStore,
  type CuaPreviewPosition,
  type CuaPreviewSession
} from '../../store/cua-preview-store'
import { useCuaStillFrame } from './use-cua-still-frame'
import { useCuaWindowStream } from './use-cua-window-stream'

/**
 * The window computer use is operating, beside the conversation. View-only: Stop
 * stays in the composer. It docks under the operation panel and floats when that
 * column is absent or too narrow, or when the user pops it out.
 */

const MIN_DOCK_WIDTH = 200
const FLOAT_MARGIN = 8
const FLOAT_WIDTH = 480
/** How long a finished task's card stays up, marked done, before it closes. */
const ENDED_LINGER_MS = 4_000
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

function useViewportSize(): { width: number; height: number } {
  const [size, setSize] = useState({ width: window.innerWidth, height: window.innerHeight })
  useEffect(() => {
    const update = (): void => setSize({ width: window.innerWidth, height: window.innerHeight })
    window.addEventListener('resize', update)
    return () => window.removeEventListener('resize', update)
  }, [])
  return size
}

export function clampFloat(
  position: CuaPreviewPosition,
  card: { width: number; height: number },
  viewport: { width: number; height: number }
): CuaPreviewPosition {
  const maxX = Math.max(FLOAT_MARGIN, viewport.width - card.width - FLOAT_MARGIN)
  const maxY = Math.max(FLOAT_MARGIN, viewport.height - card.height - FLOAT_MARGIN)
  return {
    x: Math.min(Math.max(position.x, FLOAT_MARGIN), maxX),
    y: Math.min(Math.max(position.y, FLOAT_MARGIN), maxY)
  }
}

export function CuaPreview({ threadId }: { threadId: string | null }): ReactElement | null {
  const session = useCuaPreviewStore((state) => (threadId ? state.sessions[threadId] : undefined))
  if (!threadId || !session) return null
  // One mount per task: a new turn starts over with its own target and failures.
  return <CuaPreviewSessionView key={`${threadId}:${session.turnId ?? ''}`} threadId={threadId} session={session} />
}

function CuaPreviewSessionView({ threadId, session }: { threadId: string; session: CuaPreviewSession }): ReactElement | null {
  const { t } = useTranslation('common')
  // One canvas for the whole task, re-attached when the card docks or floats, so
  // both sources keep drawing into the same pixels and a held frame survives moves.
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
      () => { if (!cancelled) setAllowed(true) }
    )
    return () => { cancelled = true }
  }, [])
  const shown = allowed === true && phase !== 'hidden-for-task'
  const streaming = allowed === true && (phase === 'armed' || phase === 'live')

  useEffect(() => {
    if (phase === 'armed') markCuaPreviewLive(threadId)
  }, [phase, threadId])

  const live = useCuaWindowStream({
    canvasRef,
    appId: session.surface === 'app' ? session.appId : null,
    revision: session.revision,
    enabled: streaming
  })
  // The live window owns the canvas once it drew; a still never paints over it.
  const still = useCuaStillFrame({
    canvasRef, still: session.still, enabled: shown && !live.hasFrame
  })

  const frameSignal = live.hasFrame || still.status === 'ready'
  const [hasFrame, setHasFrame] = useState(frameSignal)
  if (frameSignal && !hasFrame) setHasFrame(true)
  const decoded = live.hasFrame ? live.frameSize : still.frameSize ?? live.frameSize
  const [frameSize, setFrameSize] = useState(decoded)
  if (decoded && (decoded.width !== frameSize?.width || decoded.height !== frameSize?.height)) {
    setFrameSize(decoded)
  }

  // An explicit capture problem opens the card before any frame, so it can explain.
  const problem = !hasFrame && (live.status === 'permission' || live.status === 'failed') ? live.status : null
  const visible = shown && (hasFrame || problem !== null)

  useEffect(() => {
    if (phase !== 'ended') return
    const timer = window.setTimeout(() => dismissEndedCuaPreview(threadId), hasFrame ? ENDED_LINGER_MS : 0)
    return () => window.clearTimeout(timer)
  }, [phase, hasFrame, threadId])

  const slot = useRailSlot((state) => state.slot)
  const slotUsable = useSlotUsable(slot)
  const userFloat = useCuaPreviewStore((state) => state.floating[threadId])
  const viewport = useViewportSize()
  const docked = !userFloat && slotUsable && slot !== null
  const aspect = frameSize && frameSize.height > 0 ? frameSize.width / frameSize.height : FALLBACK_ASPECT
  const floatWidth = Math.max(MIN_DOCK_WIDTH, Math.min(FLOAT_WIDTH, viewport.width - FLOAT_MARGIN * 2,
    (viewport.height - FLOAT_MARGIN * 2) * aspect))
  const floatSize = { width: floatWidth, height: floatWidth / aspect }
  const position = docked
    ? null
    : clampFloat(userFloat ?? { x: viewport.width, y: viewport.height - 96 }, floatSize, viewport)

  const cardRef = useRef<HTMLDivElement | null>(null)
  const dragOffset = useRef<{ x: number; y: number } | null>(null)
  const onPointerDown = (event: ReactPointerEvent<HTMLDivElement>): void => {
    if (!position || (event.target as Element).closest('button')) return
    event.currentTarget.setPointerCapture(event.pointerId)
    dragOffset.current = { x: event.clientX - position.x, y: event.clientY - position.y }
  }
  const onPointerMove = (event: ReactPointerEvent<HTMLDivElement>): void => {
    const offset = dragOffset.current
    if (!offset) return
    setCuaPreviewFloating(threadId, clampFloat(
      { x: event.clientX - offset.x, y: event.clientY - offset.y }, floatSize, viewport))
  }
  const onPointerEnd = (): void => {
    dragOffset.current = null
  }
  const popOut = (): void => {
    const rect = cardRef.current?.getBoundingClientRect()
    setCuaPreviewFloating(threadId, rect ? { x: rect.right - floatWidth, y: rect.top } : { x: viewport.width, y: 0 })
  }

  if (!shown) return null

  const appName = live.appName ?? (session.surface === 'browser' ? 'Chrome' : null)
  const status = phase === 'ended'
    ? t('cuaPreviewDone')
    : session.label ?? t('cuaPreviewWorking', { app: appName ?? t('cuaPreviewComputer') })

  const card = (
    <div
      ref={cardRef}
      role="region"
      aria-label={t('cuaPreviewRegion')}
      aria-hidden={visible ? undefined : true}
      data-cua-preview={threadId}
      className={`group pointer-events-auto overflow-hidden rounded-2xl border border-white/10 bg-black text-white shadow-[0_16px_48px_-16px_rgb(0_0_0/0.55),0_2px_10px_-2px_rgb(0_0_0/0.3)] transition-[opacity,transform] duration-200 ease-out motion-reduce:transition-none ${
        visible ? 'opacity-100' : 'pointer-events-none h-0 translate-y-1 border-0 opacity-0'
      } ${position ? 'fixed z-50 cursor-grab touch-none select-none active:cursor-grabbing' : 'relative w-full'}`}
      style={position ? { left: position.x, top: position.y, width: floatWidth } : undefined}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerEnd}
      onPointerCancel={onPointerEnd}
    >
      <div
        ref={(element) => {
          if (element && canvas.parentElement !== element) element.prepend(canvas)
        }}
        className="relative w-full"
        style={{ aspectRatio: frameSize ? `${frameSize.width} / ${frameSize.height}` : `${FALLBACK_ASPECT}` }}
      >
        {/* Finished edge over the captured window's antialiased fringe. */}
        <div aria-hidden className="pointer-events-none absolute inset-0 shadow-[inset_0_0_0_1px_rgb(0_0_0/0.45)]" />
        {problem ? (
          <div role="status" className="absolute inset-0 flex flex-col items-center justify-center gap-2 px-4 text-center text-[12px] text-white/75">
            <Monitor className="h-5 w-5 text-white/60" aria-hidden />
            <span>{problem === 'permission' ? t('cuaPreviewPermission') : t('cuaPreviewFailed')}</span>
            {problem === 'permission' ? (
              <button
                type="button"
                onClick={() => void window.dsGui.openScreenCaptureSettings()}
                className="rounded-full border border-white/25 px-2.5 py-0.5 text-[11px] text-white hover:bg-white/15"
              >
                {t('cuaPreviewOpenSettings')}
              </button>
            ) : null}
          </div>
        ) : null}
        <div className="pointer-events-none absolute left-2 top-2 flex max-w-[calc(100%-5.5rem)] items-center gap-1.5 rounded-full border border-white/15 bg-black/55 py-0.5 pl-0.5 pr-2 text-[11px] font-medium backdrop-blur-md">
          <span className="relative flex h-5 w-5 shrink-0 items-center justify-center">
            {live.icon ? <img src={live.icon} alt="" className="h-5 w-5" /> : <Monitor className="h-3.5 w-3.5" aria-hidden />}
            {phase === 'ended' ? (
              <span className="absolute -bottom-0.5 -right-0.5 flex h-2.5 w-2.5 items-center justify-center rounded-full bg-emerald-500">
                <Check className="h-2 w-2" strokeWidth={3.5} aria-hidden />
              </span>
            ) : null}
          </span>
          <span className="truncate">{appName ?? t('cuaPreviewComputer')}</span>
        </div>
        <div className="pointer-events-none absolute bottom-2 left-2 flex max-w-[calc(100%-1rem)] items-center gap-1.5 rounded-full border border-white/15 bg-black/55 px-2.5 py-1 text-[11px] font-medium backdrop-blur-md">
          <span
            aria-hidden
            className={`h-1.5 w-1.5 shrink-0 rounded-full ${phase === 'ended' ? 'bg-emerald-400' : 'animate-pulse bg-sky-400'}`}
          />
          <span className="truncate">{status}</span>
        </div>
        <div className="absolute right-2 top-2 flex translate-y-1 items-center gap-1 rounded-full border border-white/20 bg-black/45 p-0.5 opacity-0 backdrop-blur-md transition-[opacity,transform] duration-200 group-focus-within:translate-y-0 group-focus-within:opacity-100 group-hover:translate-y-0 group-hover:opacity-100 motion-reduce:transition-none">
          {slotUsable ? (
            <button
              type="button"
              onClick={userFloat ? () => setCuaPreviewFloating(threadId, null) : popOut}
              title={userFloat ? t('cuaPreviewDock') : t('cuaPreviewFloat')}
              aria-label={userFloat ? t('cuaPreviewDock') : t('cuaPreviewFloat')}
              className="grid h-6 w-6 place-items-center rounded-full hover:bg-white/20"
            >
              {userFloat ? <Minimize2 className="h-3.5 w-3.5" /> : <Maximize2 className="h-3.5 w-3.5" />}
            </button>
          ) : null}
          <button
            type="button"
            onClick={() => hideCuaPreviewForTask(threadId)}
            title={t('cuaPreviewHide')}
            aria-label={t('cuaPreviewHide')}
            className="grid h-6 w-6 place-items-center rounded-full hover:bg-white/20"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    </div>
  )
  // Until its first frame the card waits out of the rail, so the dock does not shift.
  return createPortal(card, docked && visible && slot ? slot : document.body)
}
