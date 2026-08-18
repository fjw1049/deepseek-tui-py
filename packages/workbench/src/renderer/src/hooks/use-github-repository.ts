import { useCallback, useEffect, useRef, useState } from 'react'
import type { GitHubRepositoryResult } from '@shared/github-repository'

export function useGitHubRepository(workspaceRoot: string): {
  result: GitHubRepositoryResult | null
  reload: () => Promise<void>
} {
  const root = workspaceRoot.trim()
  const [result, setResult] = useState<GitHubRepositoryResult | null>(null)
  const rootRef = useRef(root)
  rootRef.current = root

  const reload = useCallback(async (): Promise<void> => {
    if (!root || typeof window.dsGui?.getGitHubRepository !== 'function') {
      setResult(null)
      return
    }

    const requestRoot = root
    try {
      const next = await window.dsGui.getGitHubRepository(requestRoot)
      if (rootRef.current !== requestRoot) return
      setResult(next)
    } catch {
      if (rootRef.current !== requestRoot) return
      setResult(null)
    }
  }, [root])

  useEffect(() => {
    setResult(null)
    void reload()
  }, [reload, root])

  return { result, reload }
}
