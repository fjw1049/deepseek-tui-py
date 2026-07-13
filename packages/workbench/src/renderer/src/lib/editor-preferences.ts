export const PREFERRED_EDITOR_STORAGE_KEY = 'deepseekgui.editor.preferredId'
export const PREFERRED_EDITOR_CHANGED_EVENT = 'deepseekgui:preferred-editor-changed'

export function readPreferredEditorId(): string | undefined {
  try {
    const value = window.localStorage.getItem(PREFERRED_EDITOR_STORAGE_KEY)?.trim()
    return value || undefined
  } catch {
    return undefined
  }
}

export function writePreferredEditorId(editorId: string): void {
  try {
    window.localStorage.setItem(PREFERRED_EDITOR_STORAGE_KEY, editorId)
    window.dispatchEvent(
      new CustomEvent(PREFERRED_EDITOR_CHANGED_EVENT, { detail: editorId })
    )
  } catch {
    /* ignore persistence failures */
  }
}
