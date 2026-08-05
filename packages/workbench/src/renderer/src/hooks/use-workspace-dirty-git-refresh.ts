import { useEffect, useRef } from 'react'

/**
 * Debounce-reload git (or other workspace) state when `workspaceDirtyTick` bumps.
 * Skips tick 0 so the consumer's own mount reload is not doubled.
 *
 * Trailing debounce with a max wait: a steady stream of ticks (parallel tool
 * calls, fs-watch events during builds) keeps resetting the quiet window, so
 * without the cap the refresh could be postponed indefinitely.
 */
export function useWorkspaceDirtyGitRefresh(
  workspaceDirtyTick: number,
  reload: () => void | Promise<void>,
  delayMs = 500,
  maxWaitMs = 2000
): void {
  // Epoch of the first tick of the current burst; 0 = no pending reload.
  const burstStartRef = useRef(0)

  useEffect(() => {
    if (workspaceDirtyTick <= 0) return
    const now = Date.now()
    if (burstStartRef.current === 0) burstStartRef.current = now
    const remainingBudget = Math.max(0, burstStartRef.current + maxWaitMs - now)
    const handle = window.setTimeout(
      () => {
        burstStartRef.current = 0
        void reload()
      },
      Math.min(delayMs, remainingBudget)
    )
    return () => window.clearTimeout(handle)
  }, [delayMs, maxWaitMs, reload, workspaceDirtyTick])
}
