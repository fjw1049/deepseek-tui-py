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
) {
  const [attempt, setAttempt] = useState(0)
  const retry = () => setAttempt((value) => value + 1)
  const key = threadId ? `${threadId}\u0000${refreshKey}\u0000${attempt}` : ''
  const [state, setState] = useState<ComparisonState>({ key: '', files: null })

  useEffect(() => {
    if (!threadId) return
    const provider = getProvider(useChatStore.getState().providerId)
    if (typeof provider.getPublishComparison !== 'function') {
      setState({ key, files: null })
      return
    }
    let cancelled = false
    void provider
      .getPublishComparison(threadId)
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
      .catch(() => {
        if (!cancelled) setState({ key, files: null })
      })
    return () => {
      cancelled = true
    }
  }, [key, threadId])

  const current = Boolean(threadId) && state.key === key
  return {
    files: current ? state.files : null,
    loading: Boolean(threadId) && !current,
    failed: current && state.files === null,
    retry
  }
}
