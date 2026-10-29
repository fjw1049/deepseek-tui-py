import { expect, it, vi } from 'vitest'
import { enqueueViewportRender } from './viewport-render-queue'
it('admits one message per frame and removes cancelled work', () => {
  const frames: FrameRequestCallback[] = []
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => { frames.push(callback); return frames.length })
  vi.stubGlobal('cancelAnimationFrame', vi.fn())
  const first = vi.fn(), second = vi.fn(), removed = vi.fn()
  try {
    enqueueViewportRender(first)
    const cancel = enqueueViewportRender(removed)
    enqueueViewportRender(second)
    cancel()
    frames.shift()!(0)
    expect(first).toHaveBeenCalledOnce()
    expect(second).not.toHaveBeenCalled()
    frames.shift()!(16)
    expect(second).toHaveBeenCalledOnce()
    expect(removed).not.toHaveBeenCalled()
  } finally { vi.unstubAllGlobals() }
})
