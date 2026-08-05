import { useEffect } from 'react'
import { useChatStore } from '../store/chat-store'

/**
 * Watch the active workspace on disk (main-process fs watcher) and bump
 * `workspaceDirtyTick` when files change, so the git panels also refresh on
 * edits made outside the agent: external editors (Cursor, VS Code…), manual
 * saves, and shell commands still mid-run.
 */
export function useWorkspaceFsWatch(): void {
  const workspaceRoot = useChatStore((s) => s.workspaceRoot)

  useEffect(() => {
    const root = workspaceRoot.trim()
    const gui = window.dsGui
    if (
      !root ||
      typeof gui?.watchWorkspaceFs !== 'function' ||
      typeof gui?.onWorkspaceFsChanged !== 'function'
    ) {
      return
    }
    void gui.watchWorkspaceFs(root)
    const off = gui.onWorkspaceFsChanged((payload) => {
      if (!payload || payload.root !== root) return
      useChatStore.setState((s) => ({ workspaceDirtyTick: s.workspaceDirtyTick + 1 }))
    })
    return () => {
      off()
      if (typeof gui.unwatchWorkspaceFs === 'function') void gui.unwatchWorkspaceFs()
    }
  }, [workspaceRoot])
}
