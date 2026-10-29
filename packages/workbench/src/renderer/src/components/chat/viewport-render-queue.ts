// One new heavy message per animation frame; nearby messages share this queue.
const pending = new Set<() => void>()
let frame: number | null = null
function schedule(): void {
  if (frame !== null || pending.size === 0) return
  frame = requestAnimationFrame(() => {
    frame = null
    const task = pending.values().next().value
    if (task) { pending.delete(task); task() }
    schedule()
  })
}
export function enqueueViewportRender(task: () => void): () => void {
  pending.add(task)
  schedule()
  return () => {
    pending.delete(task)
    if (pending.size === 0 && frame !== null) {
      cancelAnimationFrame(frame)
      frame = null
    }
  }
}
