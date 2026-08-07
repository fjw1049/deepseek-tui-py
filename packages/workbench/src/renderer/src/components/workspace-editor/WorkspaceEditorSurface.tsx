import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
  type ReactElement
} from 'react'
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

export type WorkspaceEditorSurfaceHandle = {
  openFind: () => void
}

type Props = {
  tab: EditorTab
  patch?: string
  readOnly: boolean
  onChange: (content: string) => void
  /** Open Monaco find once the editor is ready (e.g. after leaving markdown preview). */
  openFindOnReady?: boolean
}

export const WorkspaceEditorSurface = forwardRef<WorkspaceEditorSurfaceHandle, Props>(
  function WorkspaceEditorSurface(
    { tab, patch, readOnly, onChange, openFindOnReady = false },
    ref
  ): ReactElement {
    const hostRef = useRef<HTMLDivElement>(null)
    const editorRef = useRef<MonacoEditor.IStandaloneCodeEditor | null>(null)
    const cleanupRef = useRef<(() => void) | null>(null)
    const pendingFindRef = useRef(false)
    const [editorReady, setEditorReady] = useState(false)

    const openFind = useCallback((): void => {
      const editor = editorRef.current
      if (!editor) {
        pendingFindRef.current = true
        return
      }
      editor.focus()
      const action = editor.getAction('actions.find')
      if (action) {
        void action.run()
        return
      }
      editor.trigger('keyboard', 'actions.find', null)
    }, [])

    useImperativeHandle(ref, () => ({ openFind }), [openFind])

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
      if (typeof line !== 'number' || !Number.isFinite(line) || line < 1) return
      const editor = editorRef.current
      if (!editor) return
      let cancelled = false
      const reveal = (): void => {
        if (cancelled) return
        const model = editor.getModel()
        if (!model || model.getLineCount() < 1) return
        const target = Math.min(Math.max(1, Math.floor(line)), model.getLineCount())
        editor.revealLineInCenter(target)
        editor.setPosition({ lineNumber: target, column: tab.column ?? 1 })
      }
      // Defer past Monaco's controlled `value` sync + layout. Otherwise the
      // model rewrite after loading snaps the viewport back to line 1.
      const frame = window.requestAnimationFrame(() => {
        window.requestAnimationFrame(reveal)
      })
      return () => {
        cancelled = true
        window.cancelAnimationFrame(frame)
      }
    }, [editorReady, tab.id, tab.line, tab.column, tab.loading, tab.revealNonce])

    useEffect(() => {
      if (!editorReady || tab.loading) return
      if (!openFindOnReady && !pendingFindRef.current) return
      pendingFindRef.current = false
      const frame = window.requestAnimationFrame(() => openFind())
      return () => window.cancelAnimationFrame(frame)
    }, [editorReady, tab.loading, openFindOnReady, openFind])

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
            find: {
              addExtraSpaceOnTop: false,
              autoFindInSelection: 'never',
              seedSearchStringFromSelection: 'always'
            },
            minimap: { enabled: false },
            // Side-panel editor is short; sticky scope headers read as a heavy
            // "black bar" in dark theme (vs-dark shadow + widget bg).
            stickyScroll: { enabled: false },
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
)
