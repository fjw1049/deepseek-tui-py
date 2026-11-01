import { useEffect, useState, type RefObject } from 'react'
import type { CuaPreviewStill } from '../../store/cua-preview-store'

/**
 * Fallback source for when the live stream has no frame of its own, drawn into the same
 * canvas: what the runtime sees right now, else the latest screenshot a call recorded.
 * The runtime needs no Screen Recording grant from this app, so a permission gap or a
 * browser target still shows every step.
 */
export type CuaStillState = {
  status: 'idle' | 'loading' | 'ready' | 'error'
  frameSize: { width: number; height: number } | null
}

type FramePayload = { data?: unknown; mime_type?: unknown }

async function readFrame(path: string): Promise<FramePayload | null> {
  const response = await window.dsGui.runtimeRequest(path, 'GET')
  return response.ok ? JSON.parse(response.body) as FramePayload : null
}

export function useCuaStillFrame(input: {
  canvasRef: RefObject<HTMLCanvasElement | null>
  still: CuaPreviewStill | null
  enabled: boolean
  /** Where to ask for the current frame while the task runs; null once it has ended. */
  currentPath: string | null
  /** Changes with every finished step. */
  refresh: number
}): CuaStillState {
  const { canvasRef, still, enabled, currentPath, refresh } = input
  const [state, setState] = useState<CuaStillState>({ status: 'idle', frameSize: null })
  const itemId = still?.itemId
  const assetId = still?.assetId

  useEffect(() => {
    if (!enabled || (!currentPath && (!itemId || !assetId))) return
    let cancelled = false
    setState((previous) => ({ ...previous, status: 'loading' }))
    void (async () => {
      try {
        const current = currentPath ? await readFrame(currentPath).catch(() => null) : null
        if (cancelled) return
        const frame = current ?? (itemId && assetId
          ? await readFrame(`/v1/cua/frames/${encodeURIComponent(itemId)}/${encodeURIComponent(assetId)}`)
          : undefined)
        if (cancelled) return
        // Between calls there may simply be no frame yet; that is not a failure.
        if (frame === undefined) {
          setState((previous) => ({ ...previous, status: previous.frameSize ? 'ready' : 'idle' }))
          return
        }
        if (typeof frame?.data !== 'string') throw new Error('frame payload')
        const bytes = Uint8Array.from(atob(frame.data), (char) => char.charCodeAt(0))
        const type = typeof frame.mime_type === 'string' ? frame.mime_type : 'image/jpeg'
        const bitmap = await createImageBitmap(new Blob([bytes], { type }))
        try {
          const canvas = canvasRef.current
          const context = canvas?.getContext('2d')
          if (cancelled || !canvas || !context) return
          canvas.width = bitmap.width
          canvas.height = bitmap.height
          context.drawImage(bitmap, 0, 0)
          setState({ status: 'ready', frameSize: { width: bitmap.width, height: bitmap.height } })
        } finally {
          bitmap.close()
        }
      } catch {
        // A missing still keeps whatever the canvas already shows.
        if (!cancelled) setState((previous) => ({ ...previous, status: 'error' }))
      }
    })()
    return () => {
      cancelled = true
    }
  }, [canvasRef, enabled, itemId, assetId, currentPath, refresh])

  return state
}
