import type { EditorOpenResult } from '@shared/editor'
import { readPreferredEditorId } from './editor-preferences'

export type WorkspacePathTarget = {
  path: string
  line?: number
  column?: number
}

export async function openWorkspacePathInEditor(
  target: WorkspacePathTarget,
  workspaceRoot?: string
): Promise<EditorOpenResult> {
  if (typeof window.dsGui?.openEditorPath !== 'function') {
    return { ok: false, message: 'Editor bridge is unavailable.' }
  }

  return window.dsGui.openEditorPath({
    path: target.path,
    line: target.line,
    column: target.column,
    workspaceRoot,
    editorId: readPreferredEditorId()
  })
}

export const openWorkspacePath = openWorkspacePathInEditor

export async function revealWorkspacePathInFolder(path: string): Promise<EditorOpenResult> {
  if (typeof window.dsGui?.showItemInFolder === 'function') {
    try {
      await window.dsGui.showItemInFolder(path)
      return { ok: true, path, editorId: 'finder' }
    } catch (error) {
      return {
        ok: false,
        message: error instanceof Error ? error.message : String(error)
      }
    }
  }
  if (typeof window.dsGui?.openEditorPath !== 'function') {
    return { ok: false, message: 'Reveal bridge is unavailable.' }
  }
  return window.dsGui.openEditorPath({ path, editorId: 'finder' })
}

export async function resolvePreferredEditorLabel(fallback = 'Editor'): Promise<string> {
  if (typeof window.dsGui?.listEditors !== 'function') return fallback
  try {
    const result = await window.dsGui.listEditors()
    const available = result.editors.filter(
      (editor) => editor.available && editor.id !== 'system'
    )
    const stored = readPreferredEditorId()
    const storedOk =
      Boolean(stored) && stored !== 'system' && available.some((editor) => editor.id === stored)
    const preferredId = storedOk
      ? stored!
      : available.some((editor) => editor.id === result.defaultEditorId)
        ? result.defaultEditorId
        : available.find((editor) => editor.kind === 'editor')?.id
    const match =
      available.find((editor) => editor.id === preferredId) ??
      available.find((editor) => editor.kind === 'editor') ??
      available[0]
    return match?.label?.trim() || fallback
  } catch {
    return fallback
  }
}
