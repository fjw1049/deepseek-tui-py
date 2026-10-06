import type { BrowserWindow } from 'electron'
import { MAX_WINDOW_BLUR_RADIUS, MIN_WINDOW_BLUR_RADIUS, type WindowMaterial } from '../shared/appearance'

export type WindowMaterialAddon = {
  setBackgroundBlurRadius: (handle: Buffer, radius: number) => boolean
}

export function parseWindowMaterial(raw: unknown): WindowMaterial | null {
  if (!raw || typeof raw !== 'object') return null
  const { material, blurRadius } = raw as Record<string, unknown>
  if (material !== 'opaque' && material !== 'translucent') return null
  if (typeof blurRadius !== 'number' || !Number.isFinite(blurRadius)) return null
  return {
    material,
    blurRadius: material === 'opaque' ? 0 : Math.round(Math.min(MAX_WINDOW_BLUR_RADIUS, Math.max(MIN_WINDOW_BLUR_RADIUS, blurRadius)))
  }
}

/** Load only when a custom radius is requested; Auto retains the existing system material. */
export function createWindowMaterialApplier(loadAddon: () => WindowMaterialAddon | null) {
  let addon: WindowMaterialAddon | null | undefined
  return (window: Pick<BrowserWindow, 'setVibrancy' | 'getNativeWindowHandle'>, input: WindowMaterial): boolean => {
    if (input.material === 'opaque') {
      addon?.setBackgroundBlurRadius(window.getNativeWindowHandle(), 0)
      window.setVibrancy('under-window')
      return true
    }
    if (addon === undefined) addon = loadAddon()
    if (addon) {
      window.setVibrancy(null)
      try {
        if (addon.setBackgroundBlurRadius(window.getNativeWindowHandle(), input.blurRadius)) return true
      } catch {
        // A rejected native request must never leave the sidebar without its backing.
      }
    }
    window.setVibrancy('under-window')
    return false
  }
}
