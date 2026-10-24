import { useEffect, useRef, useState, type RefObject } from 'react'
import type { CuaPreviewWindowResult } from '../../../../shared/ds-gui-api'

/** Live capture of the one window computer use is operating, drawn into a canvas. */

export const LIVE_MAX_SIDE = 960
export const LIVE_MAX_FPS = 15

export type CuaStreamStatus = 'idle' | CuaPreviewWindowResult['status'] | 'failed'

export type CuaWindowStreamState = {
  status: CuaStreamStatus
  /** A live frame has been drawn since the current stream started. */
  hasFrame: boolean
  frameSize: { width: number; height: number } | null
  appName: string | null
  icon: string | null
}

const IDLE: CuaWindowStreamState = { status: 'idle', hasFrame: false, frameSize: null, appName: null, icon: null }

type VideoWithFrames = HTMLVideoElement & {
  requestVideoFrameCallback?: (callback: () => void) => number
}

/** A just-launched app may not show its window yet: look once more after this long. */
export const NO_WINDOW_RECHECK_MS = 1_500

/**
 * One capture at a time, for one exact window. A source that failed or ended is
 * not retried for the rest of the task (the hook's lifetime); a new window of the
 * app, found on the next call, may start a new stream. Re-checking the same window
 * never restarts its capture, even while that capture is still starting.
 */
class WindowStream {
  private stream: MediaStream | null = null
  /** The window being captured or starting to be captured. */
  private sourceId: string | null = null
  private appId: string | null = null
  /** Newest window lookup wins; older lookups are ignored when they return. */
  private generation = 0
  /** Owner of the capture slot; bumped whenever the capture is replaced or stopped. */
  private captureToken = 0
  private recheck: number | null = null
  private readonly dead = new Set<string>()

  constructor(
    private readonly canvas: () => HTMLCanvasElement | null,
    private readonly report: (patch: Partial<CuaWindowStreamState>) => void
  ) {}

  async target(appId: string, recheckIfMissing = true): Promise<void> {
    this.clearRecheck()
    const generation = ++this.generation
    let result: CuaPreviewWindowResult
    try {
      result = await window.dsGui.resolveCuaPreviewWindow(appId)
    } catch {
      result = { status: 'unsupported' }
    }
    if (generation !== this.generation) return
    this.report({ appName: result.appName ?? null, icon: result.icon ?? null })
    const sourceId = result.status === 'ok' ? result.sourceId ?? null : null
    if (!sourceId) {
      // The same app's stream keeps running until its own window goes away; another
      // app's stream must never stand in for the newly touched one.
      if (this.sourceId && this.appId === appId) return
      this.stopCapture()
      this.report({ status: result.status === 'ok' ? 'no-window' : result.status, hasFrame: false })
      if (recheckIfMissing && result.status === 'no-window') {
        this.recheck = window.setTimeout(() => void this.target(appId, false), NO_WINDOW_RECHECK_MS)
      }
      return
    }
    if (this.sourceId === sourceId || this.dead.has(sourceId)) return
    this.stopCapture()
    const token = this.captureToken
    this.sourceId = sourceId
    this.appId = appId
    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: {
          mandatory: {
            chromeMediaSource: 'desktop',
            chromeMediaSourceId: sourceId,
            maxWidth: LIVE_MAX_SIDE,
            maxHeight: LIVE_MAX_SIDE,
            maxFrameRate: LIVE_MAX_FPS
          }
        } as MediaTrackConstraints
      })
    } catch {
      this.dead.add(sourceId)
      if (token !== this.captureToken) return
      this.sourceId = null
      this.appId = null
      this.report({ status: 'failed', hasFrame: false })
      return
    }
    if (token !== this.captureToken) {
      stream.getTracks().forEach((track) => track.stop())
      return
    }
    this.stream = stream
    this.report({ status: 'ok', hasFrame: false })
    stream.getVideoTracks()[0]?.addEventListener('ended', () => {
      if (this.stream !== stream) return
      // The window closed: remember it and wait for the next call to find another.
      this.dead.add(sourceId)
      this.stopCapture()
      this.report({ status: 'no-window', hasFrame: false })
    })
    this.draw(stream)
  }

  private draw(stream: MediaStream): void {
    const video = document.createElement('video') as VideoWithFrames
    video.muted = true
    video.playsInline = true
    video.srcObject = stream
    let last = 0
    const frame = (): void => {
      if (this.stream !== stream) return
      const now = performance.now()
      const canvas = this.canvas()
      const context = canvas?.getContext('2d')
      // Frames arriving faster than the preview rate are dropped, never queued.
      if (canvas && context && video.videoWidth > 0 && now - last >= 1000 / LIVE_MAX_FPS) {
        last = now
        const { videoWidth: width, videoHeight: height } = video
        if (canvas.width !== width || canvas.height !== height) {
          canvas.width = width
          canvas.height = height
        }
        context.drawImage(video, 0, 0, width, height)
        this.report({ hasFrame: true, frameSize: { width, height } })
      }
      schedule()
    }
    const schedule = (): void => {
      if (this.stream !== stream) return
      if (video.requestVideoFrameCallback) video.requestVideoFrameCallback(frame)
      else window.setTimeout(frame, 1000 / LIVE_MAX_FPS)
    }
    void video.play().then(schedule, () => undefined)
  }

  private clearRecheck(): void {
    if (this.recheck !== null) window.clearTimeout(this.recheck)
    this.recheck = null
  }

  private stopCapture(): void {
    this.captureToken += 1
    this.stream?.getTracks().forEach((track) => track.stop())
    this.stream = null
    this.sourceId = null
    this.appId = null
    // The canvas keeps its last frame: stills or the next stream paint over it.
  }

  stop(): void {
    this.generation += 1
    this.clearRecheck()
    this.stopCapture()
  }
}

export function useCuaWindowStream(input: {
  canvasRef: RefObject<HTMLCanvasElement | null>
  appId: string | null
  /** Changes with every finished call, so the app's current window is re-checked. */
  revision: number
  enabled: boolean
}): CuaWindowStreamState {
  const { canvasRef, appId, revision, enabled } = input
  const [state, setState] = useState<CuaWindowStreamState>(IDLE)
  const controller = useRef<WindowStream | null>(null)
  const [pageVisible, setPageVisible] = useState(() => document.visibilityState !== 'hidden')

  useEffect(() => {
    const update = (): void => setPageVisible(document.visibilityState !== 'hidden')
    document.addEventListener('visibilitychange', update)
    return () => document.removeEventListener('visibilitychange', update)
  }, [])

  useEffect(() => {
    const stream = new WindowStream(
      () => canvasRef.current,
      (patch) =>
        setState((previous) => {
          const next = { ...previous, ...patch }
          const same = (Object.keys(patch) as Array<keyof CuaWindowStreamState>).every((key) =>
            key === 'frameSize'
              ? previous.frameSize?.width === next.frameSize?.width &&
                previous.frameSize?.height === next.frameSize?.height
              : previous[key] === next[key]
          )
          return same ? previous : next
        })
    )
    controller.current = stream
    return () => {
      stream.stop()
      controller.current = null
    }
  }, [canvasRef])

  const active = enabled && pageVisible && appId !== null && window.dsGui.platform === 'darwin'
  useEffect(() => {
    if (!active || !appId) {
      // Stopping keeps hasFrame: the held frame stays on the canvas instead of an older still.
      controller.current?.stop()
      setState((previous) => (previous.status === 'idle' ? previous : { ...previous, status: 'idle' }))
      return
    }
    void controller.current?.target(appId)
  }, [active, appId, revision])

  return state
}
