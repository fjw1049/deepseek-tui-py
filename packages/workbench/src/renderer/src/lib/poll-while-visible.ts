/**
 * `setInterval` that skips ticks while the window is hidden (minimised or
 * fully occluded) and catches up with one immediate tick when it becomes
 * visible again. Background polling otherwise keeps waking the renderer and
 * the runtime for UI nobody can see.
 */
export function pollWhileVisible(tick: () => void, intervalMs: number): () => void {
  const hidden = (): boolean =>
    typeof document !== 'undefined' && document.visibilityState === 'hidden'
  const timer = window.setInterval(() => {
    if (!hidden()) tick()
  }, intervalMs)
  const onVisibilityChange = (): void => {
    if (!hidden()) tick()
  }
  document.addEventListener('visibilitychange', onVisibilityChange)
  return () => {
    window.clearInterval(timer)
    document.removeEventListener('visibilitychange', onVisibilityChange)
  }
}
