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
import { useWorkspaceViewPreferences } from '../../store/workspace-view-preferences'
import { subscribeAppearance } from '../../lib/apply-appearance'
import type { editor as MonacoEditor } from 'monaco-editor'
import { applyEditorDiffHighlights } from '../../lib/apply-editor-diff-highlights'
import {
  ensureMonacoConfigured,
  ensureWorkspaceMonacoThemes,
  workspaceMonacoTheme,
  type WorkspaceMonacoThemeName
} from '../../lib/monaco-editor-setup'
import { languageForPath } from '../../lib/monaco-language-for-path'
import { workspaceModelPath, pruneClosedWorkspaceModels } from '../../lib/workspace-monaco-models'
import type { EditorPaneId, EditorTab } from '../../store/workspace-editor-store'
import { EditorListSkeleton } from './EditorListSkeleton'

ensureMonacoConfigured()
ensureWorkspaceMonacoThemes()

export type WorkspaceEditorSurfaceHandle = {
  openFind: () => void
  getSelectionRange: () => { startLine: number; endLine: number } | null
}

type Props = {
  paneId: EditorPaneId
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
    { paneId, tab, patch, readOnly, onChange, openFindOnReady = false, onQuoteSelection },
    ref
  ): ReactElement {
    const wrapLines = useWorkspaceViewPreferences((s) => s.wrapLines)
    const hostRef = useRef<HTMLDivElement>(null)
    const editorRef = useRef<MonacoEditor.IStandaloneCodeEditor | null>(null)
    const cleanupRef = useRef<(() => void) | null>(null)
    const pendingFindRef = useRef(false)
    const revealedRequestsRef = useRef(new Map<string, string>())
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

    useEffect(() => pruneClosedWorkspaceModels, [])

    useEffect(() => {
      cleanupRef.current?.()
      cleanupRef.current = null
    }, [tab.id])

    useEffect(() => {
      editorRef.current?.updateOptions({ readOnly })
    }, [readOnly])

    useEffect(() => {
      const editor = editorRef.current
      const model = editor?.getModel()
      if (!editorReady || !editor || !model || model.getValue() === tab.content) return
      // The React wrapper's controlled read-only value resets the cursor even
      // when a retained model already contains that value. Sync actual changes only.
      if (readOnly) model.setValue(tab.content)
      else editor.executeEdits('workspace-sync', [{ range: model.getFullModelRange(), text: tab.content }])
    }, [editorReady, tab.id, tab.content, readOnly])

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
    }, [editorReady, syncHighlights, tab.loading, patch, tab.id])

    // Monaco measures glyphs independently of the surrounding UI CSS.
    useEffect(() => {
      if (!editorReady) return
      const syncAppearance = (): void => {
        setMonacoTheme(workspaceMonacoTheme(Boolean(hostRef.current?.closest('.ds-ide-workspace'))))
        const fontFamily = getComputedStyle(document.documentElement)
          .getPropertyValue('--font-mono')
          .trim()
        editorRef.current?.updateOptions({ fontFamily })
      }
      syncAppearance()
      const unsubscribe = subscribeAppearance(syncAppearance)
      const observer = new MutationObserver(syncAppearance)
      observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
      return () => {
        unsubscribe()
        observer.disconnect()
      }
    }, [editorReady, tab.id])

    // Honor "open at line N" requests (e.g. a file-edit tool card). Deps are the
    // tab/line primitives only, so typing, scrolling, or content updates never
    // re-trigger a reveal — it fires on mount and on actual tab/line changes.
    useEffect(() => {
      if (!editorReady || tab.loading) return
      const line = tab.line
      if (typeof line !== 'number' || !Number.isFinite(line) || line < 1) return
      const request = `${tab.revealNonce ?? 0}:${line}:${tab.column ?? 1}`
      if (revealedRequestsRef.current.get(tab.id) === request) return
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
        revealedRequestsRef.current.set(tab.id, request)
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
          path={workspaceModelPath(tab.id, paneId)}
          keepCurrentModel
          height="100%"
          width="100%"
          wrapperProps={{ className: 'absolute inset-0 overflow-hidden' }}
          theme={monacoTheme}
          language={languageForPath(tab.path)}
          defaultValue={tab.content}
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
            hover: { enabled: !readOnly, delay: 500 },
            find: {
              addExtraSpaceOnTop: false,
              autoFindInSelection: 'never',
              seedSearchStringFromSelection: 'always'
            },
            minimap: { enabled: false },
            showUnused: false,
            bracketPairColorization: { enabled: false },
            // Side-panel editor is short; sticky scope headers read as a heavy
            // "black bar" in dark theme (vs-dark shadow + widget bg).
            stickyScroll: { enabled: false },
            overviewRulerLanes: 0,
            hideCursorInOverviewRuler: true,
            overviewRulerBorder: false,
            glyphMargin: false,
            lineDecorationsWidth: 12,
            lineNumbersMinChars: 3,
            renderLineHighlight: readOnly ? 'none' : 'line',
            fontSize: 15,
            lineHeight: 23,
            scrollBeyondLastLine: false,
            automaticLayout: false,
            wordWrap: (wrapLines ?? (languageForPath(tab.path) === 'plaintext')) ? 'on' : 'off',
            // Top/bottom breathing matches the user message bubble (0.6rem ≈ 10px),
            // so the editor's first/last line sits at the same rhythm as chat prose.
            padding: { top: 10, bottom: 10 },
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
