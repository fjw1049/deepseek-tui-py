import { useEffect, useState } from 'react'
import type { GitWorkingChangeFile } from '@shared/git-working-changes'
import { getProvider } from '../agent/registry'
import { useChatStore } from '../store/chat-store'

type ComparisonState = {
  key: string
  files: GitWorkingChangeFile[] | null
}

/**
 * Project -> this conversation diff for the files awaiting a version choice.
 * `refreshKey` changes whenever the runtime's choice snapshot may have moved.
 */
export function usePublishComparison(
  threadId: string | null,
  refreshKey: string
): { files: GitWorkingChangeFile[] | null; loading: boolean } {
  const key = threadId ? `${threadId}\u0000${refreshKey}` : ''
  const [state, setState] = useState<ComparisonState>({ key: '', files: null })

  useEffect(() => {
    if (!threadId) return
    const provider = getProvider(useChatStore.getState().providerId)
    if (typeof provider.getPublishComparison !== 'function') {
      setState({ key, files: [] })
      return
    }
    let cancelled = false
    void provider
      .getPublishComparison(threadId)
      .catch(() => [])
      .then((files) => {
        if (cancelled) return
        setState({
          key,
          files: files.map((file) => ({
            path: file.path,
            status: file.status,
            stage: 'unstaged',
            patch: file.patch
          }))
        })
      })
    return () => {
      cancelled = true
    }
  }, [key, threadId])

  if (!threadId) return { files: null, loading: false }
  return state.key === key
    ? { files: state.files, loading: false }
    : { files: null, loading: true }
}
