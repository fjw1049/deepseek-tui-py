/** Keep the latest visual update when pointer events arrive faster than frames. */
export function createFrameQueue(): { queue: (apply: () => void) => void; flush: () => void } {
  let frame: number | null = null
  let pending: (() => void) | null = null

  const flush = (): void => {
    if (frame !== null) cancelAnimationFrame(frame)
    frame = null
    const apply = pending
    pending = null
    apply?.()
  }

  return {
    queue(apply) {
      pending = apply
      if (frame === null) frame = requestAnimationFrame(flush)
    },
    flush
  }
}
