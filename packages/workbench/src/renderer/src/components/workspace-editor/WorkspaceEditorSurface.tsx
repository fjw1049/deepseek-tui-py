import { useCallback, useEffect, useRef, useState, type ReactElement } from 'react'
import { Loader2 } from 'lucide-react'
import Editor from '@monaco-editor/react'
import type { editor as MonacoEditor } from 'monaco-editor'
import { applyEditorDiffHighlights } from '../../lib/apply-editor-diff-highlights'
import {
  ensureMonacoConfigured,
  ensureWorkspaceMonacoThemes,
  workspaceMonacoTheme
} from '../../lib/monaco-editor-setup'
import { languageForPath } from '../../lib/monaco-language-for-path'
import type { EditorTab } from '../../store/workspace-editor-store'

ensureMonacoConfigured()
ensureWorkspaceMonacoThemes()

type Props = {
  tab: EditorTab
  patch?: string
  readOnly: boolean
  onChange: (content: string) => void
}

export function WorkspaceEditorSurface({ tab, patch, readOnly, onChange }: Props): ReactElement {
  const hostRef = useRef<HTMLDivElement>(null)
  const editorRef = useRef<MonacoEditor.IStandaloneCodeEditor | null>(null)
  const cleanupRef = useRef<(() => void) | null>(null)
  const [editorReady, setEditorReady] = useState(false)

  const syncHighlights = useCallback((): void => {
    cleanupRef.current?.()
    cleanupRef.current = null
    const editor = editorRef.current
    if (!editor) return
    cleanupRef.current = applyEditorDiffHighlights(editor, patch)
    editor.layout()
  }, [patch])

  useEffect(() => {
    setEditorReady(false)
    cleanupRef.current?.()
    cleanupRef.current = null
  }, [tab.id])

  useEffect(() => {
    editorRef.current?.updateOptions({ readOnly })
  }, [readOnly])

  useEffect(() => {
    const node = hostRef.current
    if (!node) return

    const layoutEditor = (): void => {
      editorRef.current?.layout()
    }

    layoutEditor()
    const observer = new ResizeObserver(() => layoutEditor())
    observer.observe(node)
    return () => observer.disconnect()
  }, [tab.id])

  useEffect(() => {
    if (!editorReady || tab.loading) return
    const frame = window.requestAnimationFrame(() => syncHighlights())
    return () => {
      window.cancelAnimationFrame(frame)
      cleanupRef.current?.()
      cleanupRef.current = null
    }
  }, [editorReady, syncHighlights, tab.loading, patch])

  // Honor "open at line N" requests (e.g. a file-edit tool card). Deps are the
  // tab/line primitives only, so typing, scrolling, or content updates never
  // re-trigger a reveal — it fires on mount and on actual tab/line changes.
  useEffect(() => {
    if (!editorReady || tab.loading) return
    const line = tab.line
    if (typeof line !== 'number' || !Number.isFinite(line)) return
    const editor = editorRef.current
    const model = editor?.getModel()
    if (!editor || !model) return
    const target = Math.min(Math.max(1, Math.floor(line)), model.getLineCount())
    editor.revealLineInCenter(target)
    editor.setPosition({ lineNumber: target, column: tab.column ?? 1 })
  }, [editorReady, tab.id, tab.line, tab.column, tab.loading])

  return (
    <div ref={hostRef} className="relative min-h-0 flex-1 overflow-hidden bg-ds-sidebar">
      <Editor
        key={tab.id}
        height="100%"
        width="100%"
        wrapperProps={{ className: 'absolute inset-0 overflow-hidden' }}
        theme={workspaceMonacoTheme()}
        language={languageForPath(tab.path)}
        value={tab.content}
        onChange={readOnly ? undefined : (value) => onChange(value ?? '')}
        onMount={(editor) => {
          editorRef.current = editor
          ensureWorkspaceMonacoThemes()
          editor.updateOptions({ readOnly })
          setEditorReady(true)
          editor.layout()
        }}
        loading={
          <div className="flex h-full items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-ds-faint" strokeWidth={1.8} />
          </div>
        }
        options={{
          readOnly,
          domReadOnly: readOnly,
          minimap: { enabled: false },
          overviewRulerLanes: 0,
          hideCursorInOverviewRuler: true,
          overviewRulerBorder: false,
          glyphMargin: false,
          lineDecorationsWidth: 0,
          fontSize: 13,
          lineHeight: 20,
          scrollBeyondLastLine: false,
          automaticLayout: false,
          wordWrap: 'off',
          padding: { top: 8 },
          scrollbar: {
            vertical: 'auto',
            horizontal: 'auto',
            verticalScrollbarSize: 10,
            horizontalScrollbarSize: 10,
            useShadows: false
          }
        }}
      />
    </div>
  )
}
