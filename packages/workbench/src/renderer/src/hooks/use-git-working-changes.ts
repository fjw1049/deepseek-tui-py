import { useCallback, useEffect, useRef, useState } from 'react'
import type { GitWorkingChangesResult } from '@shared/git-working-changes'

export function useGitWorkingChanges(workspaceRoot: string): {
  result: GitWorkingChangesResult | null
  loading: boolean
  reload: () => Promise<void>
} {
  const root = workspaceRoot.trim()
  const [result, setResult] = useState<GitWorkingChangesResult | null>(null)
  const [loading, setLoading] = useState(false)
  const rootRef = useRef(root)
  rootRef.current = root

  const reload = useCallback(async (): Promise<void> => {
    if (!root || typeof window.dsGui?.getGitWorkingChanges !== 'function') {
      setResult(null)
      setLoading(false)
      return
    }

    const requestRoot = root
    setLoading(true)
    try {
      const next = await window.dsGui.getGitWorkingChanges(requestRoot)
      if (rootRef.current !== requestRoot) return
      setResult(next)
      if (!next.ok && typeof window.dsGui?.logError === 'function') {
        void window.dsGui.logError('git-working-changes', next.message, {
          reason: next.reason,
          workspaceRoot: requestRoot
        })
      }
    } catch (error) {
      if (rootRef.current !== requestRoot) return
      setResult(null)
      if (typeof window.dsGui?.logError === 'function') {
        void window.dsGui.logError(
          'git-working-changes',
          'IPC getGitWorkingChanges failed',
          error instanceof Error ? error.message : String(error)
        )
      }
    } finally {
      if (rootRef.current === requestRoot) {
        setLoading(false)
      }
    }
  }, [root])

  useEffect(() => {
    setResult(null)
    setLoading(Boolean(root))
    void reload()
  }, [reload, root])

  return { result, loading, reload }
}
