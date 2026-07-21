import { useEffect } from 'react'

/**
 * Debounce-reload git (or other workspace) state when `workspaceDirtyTick` bumps.
 * Skips tick 0 so the consumer's own mount reload is not doubled.
 */
export function useWorkspaceDirtyGitRefresh(
  workspaceDirtyTick: number,
  reload: () => void | Promise<void>,
  delayMs = 500
): void {
  useEffect(() => {
    if (workspaceDirtyTick <= 0) return
    const handle = window.setTimeout(() => {
      void reload()
    }, delayMs)
    return () => window.clearTimeout(handle)
  }, [delayMs, reload, workspaceDirtyTick])
}
