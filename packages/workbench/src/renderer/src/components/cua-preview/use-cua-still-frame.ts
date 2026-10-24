import { useEffect, useState, type RefObject } from 'react'
import type { CuaPreviewStill } from '../../store/cua-preview-store'

/**
 * Fallback source: the latest screenshot a computer-use call recorded. It draws only
 * while the live window stream has no frame of its own, into the same canvas.
 */
export type CuaStillState = {
  status: 'idle' | 'loading' | 'ready' | 'error'
  frameSize: { width: number; height: number } | null
}

type FramePayload = { data?: unknown; mime_type?: unknown }

export function useCuaStillFrame(input: {
  canvasRef: RefObject<HTMLCanvasElement | null>
  still: CuaPreviewStill | null
  enabled: boolean
}): CuaStillState {
  const { canvasRef, still, enabled } = input
  const [state, setState] = useState<CuaStillState>({ status: 'idle', frameSize: null })
  const itemId = still?.itemId
  const assetId = still?.assetId

  useEffect(() => {
    if (!enabled || !itemId || !assetId) return
    let cancelled = false
    setState((previous) => ({ ...previous, status: 'loading' }))
    void (async () => {
      try {
        const response = await window.dsGui.runtimeRequest(
          `/v1/cua/frames/${encodeURIComponent(itemId)}/${encodeURIComponent(assetId)}`,
          'GET'
        )
        if (!response.ok) throw new Error(`frame ${response.status}`)
        const frame = JSON.parse(response.body) as FramePayload
        if (typeof frame.data !== 'string') throw new Error('frame payload')
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
  }, [canvasRef, enabled, itemId, assetId])

  return state
}
