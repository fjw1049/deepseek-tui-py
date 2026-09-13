import * as monaco from 'monaco-editor'
import type { editor as MonacoEditor } from 'monaco-editor'
import { parseUnifiedDiffForEditor } from './parse-unified-diff-for-editor'

/** Keep the source intact; full added/removed text belongs in the changes view. */
export function applyEditorDiffHighlights(
  editor: MonacoEditor.IStandaloneCodeEditor,
  patch: string | undefined
): () => void {
  const model = editor.getModel()
  if (!model || !patch?.trim()) return () => {}
  const { addedLines, deletionZones } = parseUnifiedDiffForEditor(patch)
  const decorations: MonacoEditor.IModelDeltaDecoration[] = addedLines
    .filter((line) => line >= 1 && line <= model.getLineCount())
    .map((line) => ({
      range: new monaco.Range(line, 1, line, 1),
      options: { linesDecorationsClassName: 'ds-editor-gutter-added' }
    }))
  for (const zone of deletionZones) {
    const line = Math.max(1, Math.min(zone.afterLineNumber, model.getLineCount()))
    decorations.push({
      range: new monaco.Range(line, 1, line, 1),
      options: { linesDecorationsClassName: zone.afterLineNumber === 0
        ? 'ds-editor-gutter-deleted ds-editor-gutter-deleted--before'
        : 'ds-editor-gutter-deleted' }
    })
  }
  const collection = editor.createDecorationsCollection(decorations)
  return () => collection.clear()
}
