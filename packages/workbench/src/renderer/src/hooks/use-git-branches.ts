import { useCallback, useEffect, useRef, useState } from 'react'
import type { GitBranchesResult } from '@shared/git-branches'

export function useGitBranches(workspaceRoot: string): {
  result: GitBranchesResult | null
  loading: boolean
  reload: () => Promise<void>
  setResult: (result: GitBranchesResult | null) => void
} {
  const root = workspaceRoot.trim()
  const [result, setResult] = useState<GitBranchesResult | null>(null)
  const [loading, setLoading] = useState(false)
  const rootRef = useRef(root)
  rootRef.current = root

  const reload = useCallback(async (): Promise<void> => {
    if (!root || typeof window.dsGui?.getGitBranches !== 'function') {
      setResult(null)
      setLoading(false)
      return
    }

    const requestRoot = root
    setLoading(true)
    try {
      const next = await window.dsGui.getGitBranches(requestRoot)
      if (rootRef.current !== requestRoot) return
      setResult(next)
    } catch {
      if (rootRef.current !== requestRoot) return
      setResult(null)
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

  return { result, loading, reload, setResult }
}
