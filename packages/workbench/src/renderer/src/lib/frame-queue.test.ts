import { expect, it, vi } from 'vitest'
import { createFrameQueue } from './frame-queue'

it('runs only the latest pointer update per frame and flushes the final one on release', () => {
  const frames = new Map<number, FrameRequestCallback>()
  let nextFrame = 0
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
    frames.set(++nextFrame, callback)
    return nextFrame
  })
  vi.stubGlobal('cancelAnimationFrame', (id: number) => frames.delete(id))
  try {
    const queue = createFrameQueue()
    const applied: number[] = []
    queue.queue(() => applied.push(1))
    queue.queue(() => applied.push(2))
    expect(frames.size).toBe(1)
    queue.flush()
    expect(applied).toEqual([2])
    expect(frames.size).toBe(0)
    queue.queue(() => applied.push(3))
    frames.get(nextFrame)?.(0)
    expect(applied).toEqual([2, 3])
  } finally {
    vi.unstubAllGlobals()
  }
})
