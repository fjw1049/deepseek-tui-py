import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react'
import type { GitChangeScope, GitWorkingChangesResult } from '@shared/git-working-changes'

const BRANCH_COMPARE_BASE_KEY = 'deepseek.gitCompareBase'
const BRANCH_COMPARE_BASE_EVENT = 'deepseekgui:branch-compare-base'

function branchCompareStorageKey(workspaceRoot: string, currentBranch: string | null): string {
  const root = workspaceRoot.trim()
  return root && currentBranch ? `${BRANCH_COMPARE_BASE_KEY}:${root}\u0000${currentBranch}` : ''
}

export function useGitBranchCompareBase(
  workspaceRoot: string,
  currentBranch: string | null
): [string | undefined, (baseRef?: string) => void] {
  const key = branchCompareStorageKey(workspaceRoot, currentBranch)
  const subscribe = useCallback(
    (onStoreChange: () => void): (() => void) => {
      if (!key) return () => undefined
      const onChange = (event: Event): void => {
        if ((event as CustomEvent<{ key?: string }>).detail?.key === key) onStoreChange()
      }
      const onStorage = (event: StorageEvent): void => {
        if (event.key === key) onStoreChange()
      }
      window.addEventListener(BRANCH_COMPARE_BASE_EVENT, onChange)
      window.addEventListener('storage', onStorage)
      return () => {
        window.removeEventListener(BRANCH_COMPARE_BASE_EVENT, onChange)
        window.removeEventListener('storage', onStorage)
      }
    },
    [key]
  )
  const getSnapshot = useCallback(
    () => (key ? window.localStorage.getItem(key) : null),
    [key]
  )
  const baseRef = useSyncExternalStore(subscribe, getSnapshot, () => null)
  const setBaseRef = useCallback(
    (next?: string): void => {
      if (!key) return
      if (next?.trim()) window.localStorage.setItem(key, next.trim())
      else window.localStorage.removeItem(key)
      window.dispatchEvent(new CustomEvent(BRANCH_COMPARE_BASE_EVENT, { detail: { key } }))
    },
    [key]
  )
  return [baseRef ?? undefined, setBaseRef]
}

export function useGitWorkingChanges(
  workspaceRoot: string,
  scope: GitChangeScope = 'working-tree',
  baseRef?: string
): {
  result: GitWorkingChangesResult | null
  loading: boolean
  reload: () => Promise<void>
} {
  const root = workspaceRoot.trim()
  const [result, setResult] = useState<GitWorkingChangesResult | null>(null)
  const [loading, setLoading] = useState(false)
  const requestedBase = scope === 'branch' ? baseRef?.trim() : undefined
  const requestKey = `${root}\u0000${scope}\u0000${requestedBase ?? ''}`
  const requestKeyRef = useRef(requestKey)
  requestKeyRef.current = requestKey

  const reload = useCallback(async (): Promise<void> => {
    if (!root || typeof window.dsGui?.getGitWorkingChanges !== 'function') {
      setResult(null)
      setLoading(false)
      return
    }

    const requestRoot = root
    const requestedScope = scope
    const requestedKey = requestKey
    setLoading(true)
    try {
      const next = await window.dsGui.getGitWorkingChanges(
        requestRoot,
        requestedScope,
        requestedBase
      )
      if (requestKeyRef.current !== requestedKey) return
      setResult(next)
      // `not_git_repo` / `no_workspace` are expected, benign states — skip them
      // so polling doesn't flood the log. The main process applies the same
      // filter for its own copy of this event.
      if (
        !next.ok &&
        next.reason !== 'not_git_repo' &&
        next.reason !== 'no_workspace' &&
        typeof window.dsGui?.logError === 'function'
      ) {
        void window.dsGui.logError('git-working-changes', next.message, {
          reason: next.reason,
          workspaceRoot: requestRoot
        })
      }
    } catch (error) {
      if (requestKeyRef.current !== requestedKey) return
      setResult(null)
      if (typeof window.dsGui?.logError === 'function') {
        void window.dsGui.logError(
          'git-working-changes',
          'IPC getGitWorkingChanges failed',
          error instanceof Error ? error.message : String(error)
        )
      }
    } finally {
      if (requestKeyRef.current === requestedKey) {
        setLoading(false)
      }
    }
  }, [requestKey, requestedBase, root, scope])

  useEffect(() => {
    setResult(null)
    setLoading(Boolean(root))
    void reload()
  }, [reload, root])

  return { result, loading, reload }
}
