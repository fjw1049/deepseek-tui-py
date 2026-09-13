import * as monaco from 'monaco-editor'
import { useWorkspaceEditorStore, type EditorPaneId } from '../store/workspace-editor-store'

// Each pane keeps its own view state and undo history while a file stays open.
const paths = new Map<string, string>()
let pruneTimer: ReturnType<typeof setTimeout> | undefined

export function workspaceModelPath(tabId: string, paneId: EditorPaneId): string {
  // An authority requires an absolute URI path; retain the full ID to avoid collisions.
  const uri = monaco.Uri.from({ scheme: 'workspace', authority: paneId, path: `/tabs/${tabId}` }).toString()
  paths.set(uri, tabId)
  return uri
}

export function pruneClosedWorkspaceModels(): void {
  clearTimeout(pruneTimer)
  // Let React detach editors before disposing models belonging to closed tabs.
  pruneTimer = setTimeout(() => {
    const openIds = new Set(useWorkspaceEditorStore.getState().tabs.map((tab) => tab.id))
    for (const [path, id] of paths) {
      if (openIds.has(id)) continue
      const model = monaco.editor.getModel(monaco.Uri.parse(path))
      if (model?.isAttachedToEditor()) continue
      model?.dispose()
      paths.delete(path)
    }
  }, 0)
}

const unsubscribe = useWorkspaceEditorStore.subscribe((state, previous) => {
  if (state.tabs.length !== previous.tabs.length || state.tabs.some((tab, i) => tab.id !== previous.tabs[i]?.id)) {
    pruneClosedWorkspaceModels()
  }
})

if (import.meta.hot) import.meta.hot.dispose(() => {
  unsubscribe()
  clearTimeout(pruneTimer)
})
