import { useEffect, useState } from 'react'
import type { ChatBlock } from '../agent/types'
import type { RunTarget } from '../store/run-panel-store'

export type RunConversation = {
  blocks: ChatBlock[]
  workspace: string
  status: string
  liveId?: string | null
}

export function useRunConversation(target: RunTarget, refresh: number, activeHint: boolean): RunConversation | null {
  const key = `${target.threadId}:${target.kind}:${target.id}`
  const [state, setState] = useState<{ key: string; value: RunConversation | null } | null>(null)
  useEffect(() => {
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const path = target.kind === 'task'
      ? `/v1/tasks/${encodeURIComponent(target.id)}/conversation`
      : `/v1/threads/${encodeURIComponent(target.threadId)}/agents/${encodeURIComponent(target.id)}/conversation`
    const load = async (): Promise<void> => {
      let poll = true
      try {
        const response = await window.dsGui.runtimeRequest(path, 'GET')
        if (cancelled) return
        if (response.ok) {
          const value = JSON.parse(response.body).conversation as RunConversation | null
          if (!value || Array.isArray(value.blocks)) {
            setState({ key, value })
            poll = value ? ['running', 'queued', 'pending'].includes(value.status) : activeHint
          }
        }
      } catch {
        // Retain the last snapshot on transient failures; legacy runs use their summary.
      } finally {
        if (!cancelled && poll) timer = setTimeout(() => void load(), 750)
      }
    }
    void load()
    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
  }, [key, target.id, target.kind, target.threadId, refresh, activeHint])
  return state?.key === key ? state.value : null
}
