import { describe, expect, it, vi } from 'vitest'
import { createWindowMaterialApplier, parseWindowMaterial } from './window-material'

describe('window material', () => {
  it('rejects malformed IPC input and limits manual blur to 1–64 points', () => {
    for (const input of [null, {}, { material: 'glass', blurRadius: 10 },
      { material: 'translucent', blurRadius: NaN }, { material: 'translucent', blurRadius: '10' }]) {
      expect(parseWindowMaterial(input)).toBeNull()
    }
    expect(parseWindowMaterial({ material: 'translucent', blurRadius: 0 })).toEqual({ material: 'translucent', blurRadius: 1 })
    expect(parseWindowMaterial({ material: 'translucent', blurRadius: 99 })).toEqual({ material: 'translucent', blurRadius: 64 })
    expect(parseWindowMaterial({ material: 'opaque', blurRadius: 64 })).toEqual({ material: 'opaque', blurRadius: 0 })
  })

  it('loads lazily, applies manual blur, and clears it when restoring Auto', () => {
    const handle = Buffer.alloc(8)
    const window = { setVibrancy: vi.fn(), getNativeWindowHandle: () => handle }
    const addon = { setBackgroundBlurRadius: vi.fn(() => true) }
    const load = vi.fn(() => addon)
    const apply = createWindowMaterialApplier(load)
    apply(window, { material: 'opaque', blurRadius: 0 })
    expect(load).not.toHaveBeenCalled()
    expect(apply(window, { material: 'translucent', blurRadius: 25 })).toBe(true)
    expect(window.setVibrancy).toHaveBeenLastCalledWith(null)
    expect(addon.setBackgroundBlurRadius).toHaveBeenLastCalledWith(handle, 25)
    apply(window, { material: 'opaque', blurRadius: 0 })
    expect(addon.setBackgroundBlurRadius).toHaveBeenLastCalledWith(handle, 0)
    expect(window.setVibrancy).toHaveBeenLastCalledWith('under-window')
    expect(load).toHaveBeenCalledOnce()
  })

  it.each(['missing', 'refused', 'throws'])('restores system material when the addon is %s', (failure) => {
    const window = { setVibrancy: vi.fn(), getNativeWindowHandle: () => Buffer.alloc(8) }
    const load = vi.fn(() => failure === 'missing' ? null : {
      setBackgroundBlurRadius: () => {
        if (failure === 'throws') throw new Error('native failure')
        return false
      }
    })
    const apply = createWindowMaterialApplier(load)
    expect(apply(window, { material: 'translucent', blurRadius: 20 })).toBe(false)
    expect(window.setVibrancy).toHaveBeenLastCalledWith('under-window')
    apply(window, { material: 'translucent', blurRadius: 30 })
    expect(load).toHaveBeenCalledOnce()
  })
})
