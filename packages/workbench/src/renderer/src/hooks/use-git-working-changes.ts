import { useCallback, useEffect, useMemo, useSyncExternalStore } from 'react'
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

type ChangesSnapshot = {
  result: GitWorkingChangesResult | null
  loading: boolean
}
type ChangesRequest = {
  snapshot: ChangesSnapshot
  listeners: Set<() => void>
  inFlight: Promise<void> | null
  reloadQueued: boolean
}

// Badge, file tree, change list and diff share the same repository snapshot.
const changesRequests = new Map<string, ChangesRequest>()
const EMPTY_CHANGES: ChangesSnapshot = { result: null, loading: false }

function changesRequest(key: string, loading: boolean): ChangesRequest {
  const existing = changesRequests.get(key)
  if (existing) return existing
  if (changesRequests.size >= 24) {
    for (const [cachedKey, request] of changesRequests) {
      if (request.listeners.size === 0 && !request.inFlight) {
        changesRequests.delete(cachedKey)
        break
      }
    }
  }
  const request: ChangesRequest = {
    snapshot: loading ? { result: null, loading: true } : EMPTY_CHANGES,
    listeners: new Set(), inFlight: null, reloadQueued: false
  }
  changesRequests.set(key, request)
  return request
}

function notifyChanges(request: ChangesRequest): void {
  for (const listener of request.listeners) listener()
}

export function useGitWorkingChanges(
  workspaceRoot: string,
  scope: GitChangeScope = 'working-tree',
  baseRef?: string
): ChangesSnapshot & { reload: () => Promise<void> } {
  const root = workspaceRoot.trim()
  const requestedBase = scope === 'branch' ? baseRef?.trim() : undefined
  const requestKey = `${root}\u0000${scope}\u0000${requestedBase ?? ''}`
  const request = useMemo(() => changesRequest(requestKey, Boolean(root)), [requestKey, root])
  const subscribe = useCallback((listener: () => void): (() => void) => {
    request.listeners.add(listener)
    return () => { request.listeners.delete(listener) }
  }, [request])
  const getSnapshot = useCallback(() => request.snapshot, [request])
  const snapshot = useSyncExternalStore(subscribe, getSnapshot, getSnapshot)

  const load = useCallback((queueRefresh: boolean): Promise<void> => {
    if (!root || typeof window.dsGui?.getGitWorkingChanges !== 'function') {
      request.snapshot = EMPTY_CHANGES
      notifyChanges(request)
      return Promise.resolve()
    }
    if (request.inFlight) {
      // A file mutation during an existing read still needs a fresh read after it.
      if (queueRefresh) request.reloadQueued = true
      return request.inFlight
    }
    request.snapshot = { ...request.snapshot, loading: true }
    request.inFlight = Promise.resolve().then(async () => {
      try {
        do {
          request.reloadQueued = false
          try {
            const next = await window.dsGui.getGitWorkingChanges(root, scope, requestedBase)
            request.snapshot = { result: next, loading: true }
            if (
              !next.ok && next.reason !== 'not_git_repo' && next.reason !== 'no_workspace' &&
              typeof window.dsGui?.logError === 'function'
            ) {
              void window.dsGui.logError('git-working-changes', next.message, {
                reason: next.reason, workspaceRoot: root
              })
            }
          } catch (error) {
            request.snapshot = { result: null, loading: true }
            if (typeof window.dsGui?.logError === 'function') {
              void window.dsGui.logError(
                'git-working-changes', 'IPC getGitWorkingChanges failed',
                error instanceof Error ? error.message : String(error)
              )
            }
          }
          notifyChanges(request)
        } while (request.reloadQueued)
      } finally {
        request.inFlight = null
        request.snapshot = { ...request.snapshot, loading: false }
        notifyChanges(request)
      }
    })
    notifyChanges(request)
    return request.inFlight
  }, [request, requestedBase, root, scope])
  const reload = useCallback(() => load(true), [load])
  useEffect(() => { void load(false) }, [load])
  return { ...snapshot, reload }
}
