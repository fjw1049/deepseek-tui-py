export const EDITOR_CLOSE_ACTIVE_TAB_EVENT = 'deepseekgui:editor-close-active-tab'
export const IDE_QUICK_OPEN_EVENT = 'deepseekgui:ide-quick-open'

export function prefetchWorkspaceFile(path: string, workspaceRoot: string): void {
  const trimmedPath = path.trim()
  const root = workspaceRoot.trim()
  if (!trimmedPath || !root) return
  if (typeof window.dsGui?.readWorkspaceFile !== 'function') return
  void window.dsGui.readWorkspaceFile({ path: trimmedPath, workspaceRoot: root }).catch(() => {
    /* warm-cache only */
  })
}
