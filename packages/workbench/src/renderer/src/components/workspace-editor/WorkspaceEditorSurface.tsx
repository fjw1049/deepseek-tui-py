import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useLayoutEffect,
  useRef,
  useState,
  type ReactElement
} from 'react'
import { MessageSquarePlus } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import Editor from '@monaco-editor/react'
import type { editor as MonacoEditor } from 'monaco-editor'
import { applyEditorDiffHighlights } from '../../lib/apply-editor-diff-highlights'
import {
  ensureMonacoConfigured,
  ensureWorkspaceMonacoThemes,
  workspaceMonacoTheme,
  type WorkspaceMonacoThemeName
} from '../../lib/monaco-editor-setup'
import { languageForPath } from '../../lib/monaco-language-for-path'
import type { EditorTab } from '../../store/workspace-editor-store'
import { EditorListSkeleton } from './EditorListSkeleton'

ensureMonacoConfigured()
ensureWorkspaceMonacoThemes()

export type WorkspaceEditorSurfaceHandle = {
  openFind: () => void
  getSelectionRange: () => { startLine: number; endLine: number } | null
}

type Props = {
  tab: EditorTab
  patch?: string
  readOnly: boolean
  onChange: (content: string) => void
  /** Open Monaco find once the editor is ready (e.g. after leaving markdown preview). */
  openFindOnReady?: boolean
  onQuoteSelection?: (startLine: number, endLine: number) => void
}

export const WorkspaceEditorSurface = forwardRef<WorkspaceEditorSurfaceHandle, Props>(
  function WorkspaceEditorSurface(
    { tab, patch, readOnly, onChange, openFindOnReady = false, onQuoteSelection },
    ref
  ): ReactElement {
    const hostRef = useRef<HTMLDivElement>(null)
    const editorRef = useRef<MonacoEditor.IStandaloneCodeEditor | null>(null)
    const cleanupRef = useRef<(() => void) | null>(null)
    const pendingFindRef = useRef(false)
    const [editorReady, setEditorReady] = useState(false)
    const [monacoTheme, setMonacoTheme] = useState<WorkspaceMonacoThemeName>(() =>
      workspaceMonacoTheme(false)
    )
    const [quoteUi, setQuoteUi] = useState<{
      top: number
      left: number
      startLine: number
      endLine: number
    } | null>(null)
    const { t } = useTranslation('common')

    // IDE workspace uses bg-app Monaco theme; chat-mode tool panel keeps sidebar.
    useLayoutEffect(() => {
      const ideCanvas = Boolean(hostRef.current?.closest('.ds-ide-workspace'))
      setMonacoTheme(workspaceMonacoTheme(ideCanvas))
    }, [tab.id])

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

    const getSelectionRange = useCallback((): { startLine: number; endLine: number } | null => {
      const editor = editorRef.current
      const selection = editor?.getSelection()
      if (!selection || selection.isEmpty()) return null
      return {
        startLine: selection.startLineNumber,
        endLine: selection.endLineNumber
      }
    }, [])

    useImperativeHandle(ref, () => ({ openFind, getSelectionRange }), [openFind, getSelectionRange])

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

    useEffect(() => {
      const editor = editorRef.current
      if (!editor || !editorReady) return
      const syncQuote = (): void => {
        const selection = editor.getSelection()
        if (!selection || selection.isEmpty()) {
          setQuoteUi(null)
          return
        }
        const visible = editor.getScrolledVisiblePosition({
          lineNumber: selection.startLineNumber,
          column: selection.startColumn
        })
        if (!visible) {
          setQuoteUi(null)
          return
        }
        setQuoteUi({
          top: Math.max(8, visible.top - 30),
          left: Math.max(8, visible.left),
          startLine: selection.startLineNumber,
          endLine: selection.endLineNumber
        })
      }
      const sel = editor.onDidChangeCursorSelection(syncQuote)
      const scroll = editor.onDidScrollChange(() => setQuoteUi(null))
      return () => {
        sel.dispose()
        scroll.dispose()
        setQuoteUi(null)
      }
    }, [editorReady, tab.id])

    return (
      <div ref={hostRef} className="relative min-h-0 flex-1 overflow-hidden bg-ds-sidebar">
        {quoteUi && onQuoteSelection ? (
          <button
            type="button"
            className="absolute z-20 inline-flex items-center gap-1 rounded-md border border-ds-border bg-ds-elevated px-1.5 py-0.5 text-[11px] font-medium text-ds-ink shadow-sm"
            style={{ top: quoteUi.top, left: quoteUi.left }}
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => {
              onQuoteSelection(quoteUi.startLine, quoteUi.endLine)
              setQuoteUi(null)
            }}
          >
            <MessageSquarePlus className="h-3 w-3" strokeWidth={1.85} />
            {t('workspaceEditorAddToChat')}
          </button>
        ) : null}
        <Editor
          key={tab.id}
          height="100%"
          width="100%"
          wrapperProps={{ className: 'absolute inset-0 overflow-hidden' }}
          theme={monacoTheme}
          language={languageForPath(tab.path)}
          value={tab.content}
          onChange={readOnly ? undefined : (value) => onChange(value ?? '')}
          onMount={(editor) => {
            editorRef.current = editor
            ensureWorkspaceMonacoThemes()
            const ideCanvas = Boolean(hostRef.current?.closest('.ds-ide-workspace'))
            const theme = workspaceMonacoTheme(ideCanvas)
            setMonacoTheme(theme)
            editor.updateOptions({ readOnly })
            setEditorReady(true)
            editor.layout()
          }}
          loading={<EditorListSkeleton />}
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
            fontSize: 12,
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
