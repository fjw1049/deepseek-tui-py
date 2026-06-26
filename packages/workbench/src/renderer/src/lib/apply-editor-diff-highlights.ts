import * as monaco from 'monaco-editor'
import type { editor as MonacoEditor } from 'monaco-editor'
import { parseUnifiedDiffForEditor } from './parse-unified-diff-for-editor'

const EDITOR_LINE_HEIGHT = 20
const DIFF_STYLE_ID = 'ds-editor-diff-styles'

const DIFF_STYLE_TEXT = `
.monaco-editor .view-lines .view-line.ds-editor-line-added,
.monaco-editor .view-lines .view-line.ds-editor-line-added .mtk1,
.monaco-editor .view-lines .view-line.ds-editor-line-added span {
  background-color: var(--ds-diff-added-soft) !important;
}
.monaco-editor .margin-view-overlays .ds-editor-line-added-margin,
.monaco-editor .margin-view-overlays .line-numbers.ds-editor-line-added-margin {
  background-color: var(--ds-diff-added-soft) !important;
}
.monaco-editor .view-line span.ds-editor-line-added-inline {
  background-color: var(--ds-diff-added-soft) !important;
  border-radius: 0;
}
`

function ensureDiffStyles(editor: MonacoEditor.IStandaloneCodeEditor): void {
  const root = editor.getDomNode()
  if (!root || root.querySelector(`#${DIFF_STYLE_ID}`)) return
  const style = document.createElement('style')
  style.id = DIFF_STYLE_ID
  style.textContent = DIFF_STYLE_TEXT
  root.appendChild(style)
}

function createDeletionZoneNode(text: string): HTMLElement {
  const root = document.createElement('div')
  root.className = 'ds-editor-deleted-block'
  for (const line of text.split('\n')) {
    const row = document.createElement('div')
    row.className = 'ds-editor-deleted-line'
    row.textContent = `- ${line}`
    root.appendChild(row)
  }
  return root
}

export function applyEditorDiffHighlights(
  editor: MonacoEditor.IStandaloneCodeEditor,
  patch: string | undefined
): () => void {
  if (!patch?.trim()) return () => {}

  ensureDiffStyles(editor)
  const model = editor.getModel()
  const { addedLines, deletionZones } = parseUnifiedDiffForEditor(patch)

  const decorationIds = editor.deltaDecorations(
    [],
    addedLines.flatMap((lineNumber) => {
      if (!model || lineNumber < 1 || lineNumber > model.getLineCount()) return []
      const maxColumn = model.getLineMaxColumn(lineNumber)
      return [
        {
          range: new monaco.Range(lineNumber, 1, lineNumber, maxColumn),
          options: {
            isWholeLine: true,
            className: 'ds-editor-line-added',
            inlineClassName: 'ds-editor-line-added-inline',
            marginClassName: 'ds-editor-line-added-margin'
          }
        }
      ]
    })
  )

  const zoneIds: string[] = []
  editor.changeViewZones((accessor) => {
    for (const zone of deletionZones) {
      const lineCount = Math.max(1, zone.text.split('\n').length)
      zoneIds.push(
        accessor.addZone({
          afterLineNumber: zone.afterLineNumber,
          heightInPx: lineCount * EDITOR_LINE_HEIGHT + 8,
          domNode: createDeletionZoneNode(zone.text)
        })
      )
    }
  })

  editor.layout()

  return () => {
    editor.deltaDecorations(decorationIds, [])
    editor.changeViewZones((accessor) => {
      for (const id of zoneIds) accessor.removeZone(id)
    })
  }
}

export function addedLineNumbersFromPatch(patch: string | undefined): number[] {
  if (!patch?.trim()) return []
  return parseUnifiedDiffForEditor(patch).addedLines
}
