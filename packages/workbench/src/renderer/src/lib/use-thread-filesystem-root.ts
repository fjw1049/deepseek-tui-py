import { useMemo } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { resolveThreadFilesystemRoot } from './workspace-path'
import { useChatStore } from '../store/chat-store'

/** Real filesystem root for the active thread (keeps /tmp workspaces). */
export function useThreadFilesystemRoot(): string {
  const { activeThreadId, threads, workspaceRoot } = useChatStore(
    useShallow((s) => ({
      activeThreadId: s.activeThreadId,
      threads: s.threads,
      workspaceRoot: s.workspaceRoot
    }))
  )
  return useMemo(
    () => resolveThreadFilesystemRoot(activeThreadId, threads, workspaceRoot),
    [activeThreadId, threads, workspaceRoot]
  )
}
