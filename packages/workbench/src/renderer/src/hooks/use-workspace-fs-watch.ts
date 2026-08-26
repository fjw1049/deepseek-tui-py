import { useEffect, useMemo } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { resolveThreadFilesystemRoot } from '../lib/workspace-path'
import { useChatStore } from '../store/chat-store'

/**
 * Watch the active workspace on disk (main-process fs watcher) and bump
 * `workspaceDirtyTick` when files change, so the git panels also refresh on
 * edits made outside the agent: external editors (Cursor, VS Code…), manual
 * saves, and shell commands still mid-run.
 *
 * Root matches the git panels (`resolveThreadFilesystemRoot`), not the
 * global settings `workspaceRoot` — a thread can sit in a different project
 * than the last-selected workspace setting.
 */
export function useWorkspaceFsWatch(): void {
  const { activeThreadId, threads, workspaceRoot } = useChatStore(
    useShallow((s) => ({
      activeThreadId: s.activeThreadId,
      threads: s.threads,
      workspaceRoot: s.workspaceRoot
    }))
  )
  const root = useMemo(
    () => resolveThreadFilesystemRoot(activeThreadId, threads, workspaceRoot),
    [activeThreadId, threads, workspaceRoot]
  )

  useEffect(() => {
    const watchRoot = root.trim()
    const gui = window.dsGui
    if (
      !watchRoot ||
      typeof gui?.watchWorkspaceFs !== 'function' ||
      typeof gui?.onWorkspaceFsChanged !== 'function'
    ) {
      return
    }
    void gui.watchWorkspaceFs(watchRoot)
    const off = gui.onWorkspaceFsChanged((payload) => {
      if (!payload || payload.root !== watchRoot) return
      useChatStore.setState((s) => ({ workspaceDirtyTick: s.workspaceDirtyTick + 1 }))
    })
    return () => {
      off()
      if (typeof gui.unwatchWorkspaceFs === 'function') void gui.unwatchWorkspaceFs()
    }
  }, [root])
}
