import type { MouseEvent as ReactMouseEvent, PointerEvent as ReactPointerEvent, ReactElement } from 'react'
import {
  forwardRef,
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState
} from 'react'
import { Columns2, Pencil, Save, Search, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { isImagePreviewPath } from '@shared/image-preview'
import { isHtmlPreviewPath } from '@shared/html-preview'
import type { ChatBlock } from '../../agent/types'
import { formatFilePathForDisplay } from '../../lib/diff-stats'
import { useGitWorkingChanges } from '../../hooks/use-git-working-changes'
import { useWorkspaceDirtyGitRefresh } from '../../hooks/use-workspace-dirty-git-refresh'
import { useChatStore } from '../../store/chat-store'
import { isMarkdownPath } from '../../lib/monaco-language-for-path'
import {
  openWorkspacePathInEditor,
  revealWorkspacePathInFolder
} from '../../lib/open-workspace-path'
import { copyableRelativePath } from '../../lib/sidebar-chrome'
import {
  formatComposerPathMention,
  insertComposerSnippet
} from '../../lib/composer-insert'
import { breadcrumbSegments, collapseBreadcrumbSegments } from '../../lib/editor-breadcrumb'
import { EDITOR_CLOSE_ACTIVE_TAB_EVENT } from '../../lib/workspace-editor-events'
import { isShortcutEnabled } from '../../lib/shortcuts-runtime'
import {
  buildWorkspaceChangePatchMap,
  lookupPatchForPath
} from '../../lib/workspace-change-patches'
import {
  normalizeEditorPathForTab,
  orderTabsByIds,
  useWorkspaceEditorStore,
  type EditorPaneId,
  type EditorTab
} from '../../store/workspace-editor-store'
import { EditorListSkeleton } from './EditorListSkeleton'
import { ImageDocumentPreview } from './ImageDocumentPreview'
import { HtmlDocumentPreview } from './HtmlDocumentPreview'
import { MarkdownDocumentPreview } from './MarkdownDocumentPreview'
import {
  WorkspaceFileContextMenu,
  type WorkspaceFileContextMenuAction
} from './WorkspaceFileContextMenu'
import { WorkspaceFileTree } from './WorkspaceFileTree'
import type { WorkspaceEditorSurfaceHandle } from './WorkspaceEditorSurface'

const LazyWorkspaceEditorSurface = lazy(() =>
  import('./WorkspaceEditorSurface').then((module) => ({
    default: module.WorkspaceEditorSurface
  }))
)

type Props = {
  workspaceRoot: string
  blocks: ChatBlock[]
  /** When true, hide the embedded file tree (IDE layout owns its own explorer/search). */
  hideTree?: boolean
}

const TREE_WIDTH_KEY = 'deepseekgui.layout.workspaceEditorTreeWidth'
const SPLIT_RATIO_KEY = 'deepseekgui.layout.workspaceEditorSplitRatio'
/** Fixed-ish explorer: wide enough for CJK names, still secondary to the editor. */
const TREE_DEFAULT = 232
const TREE_MIN = 168
const TREE_MAX = 420
const TREE_LEGACY_DEFAULT = 176
const SPLIT_DEFAULT = 0.5
const SPLIT_MIN = 0.25
const SPLIT_MAX = 0.75

type FileMenuState = {
  x: number
  y: number
  path: string
  pane?: EditorPaneId
}

function readStoredTreeWidth(): number {
  try {
    const raw = window.localStorage.getItem(TREE_WIDTH_KEY)
    if (!raw) return TREE_DEFAULT
    const parsed = Number(raw)
    if (!Number.isFinite(parsed)) return TREE_DEFAULT
    // Previous default was too tight — treat it as unset.
    if (Math.round(parsed) === TREE_LEGACY_DEFAULT) return TREE_DEFAULT
    return clampTreeWidth(parsed)
  } catch {
    return TREE_DEFAULT
  }
}

function readStoredSplitRatio(): number {
  try {
    const raw = window.localStorage.getItem(SPLIT_RATIO_KEY)
    if (!raw) return SPLIT_DEFAULT
    const parsed = Number(raw)
    if (!Number.isFinite(parsed)) return SPLIT_DEFAULT
    return Math.min(SPLIT_MAX, Math.max(SPLIT_MIN, parsed))
  } catch {
    return SPLIT_DEFAULT
  }
}

function clampTreeWidth(value: number): number {
  return Math.min(TREE_MAX, Math.max(TREE_MIN, value))
}

function fileNameFromPath(path: string): string {
  return path.split(/[/\\]/).filter(Boolean).pop() ?? path
}

function EditorSurfaceFallback(): ReactElement {
  return (
    <div className="flex min-h-0 flex-1 flex-col bg-ds-sidebar">
      <EditorListSkeleton />
    </div>
  )
}

function EditorTabMark({
  editing,
  dirty,
  changed,
  loading
}: {
  editing: boolean
  dirty: boolean
  changed: boolean
  loading: boolean
}): ReactElement | null {
  if (loading) {
    return <span className="ml-1 shrink-0 text-ds-faint">…</span>
  }
  if (editing) {
    return <span className="ml-1 shrink-0 text-[10px] text-ds-muted">✎</span>
  }
  if (dirty) {
    return <span className="ds-workspace-editor-tab__dirty" aria-hidden />
  }
  if (changed) {
    return <span className="ds-workspace-editor-tab__changed" aria-hidden />
  }
  return null
}

function EditorBreadcrumb({
  path,
  workspaceRoot
}: {
  path: string
  workspaceRoot: string
}): ReactElement {
  return (
    <div className="ds-workspace-editor-breadcrumb flex h-7 shrink-0 items-center gap-1 overflow-hidden border-b border-[color-mix(in_srgb,var(--ds-text)_10%,transparent)] px-2.5 text-[11px] text-ds-faint">
      {collapseBreadcrumbSegments(breadcrumbSegments(path, workspaceRoot)).map(
        (segment, index, all) => (
          <span key={`${segment}-${index}`} className="flex min-w-0 items-center gap-1">
            {index > 0 ? <span className="shrink-0 text-ds-faint/70">›</span> : null}
            <span
              className={
                index === all.length - 1
                  ? 'min-w-0 truncate font-medium text-ds-ink'
                  : 'shrink-0'
              }
              title={segment}
            >
              {segment}
            </span>
          </span>
        )
      )}
    </div>
  )
}

function EditorTabStrip({
  tabs,
  currentTabId,
  paneFocused,
  patchMap,
  editingTabId,
  workspaceRoot,
  emptyLabel,
  closeLabel,
  trailing,
  onSelect,
  onClose,
  onContextMenu
}: {
  tabs: EditorTab[]
  currentTabId: string | null
  paneFocused: boolean
  patchMap: ReturnType<typeof buildWorkspaceChangePatchMap>
  editingTabId: string | null
  workspaceRoot: string
  emptyLabel: string
  closeLabel: string
  trailing: ReactElement | null
  onSelect: (tabId: string) => void
  onClose: (tabId: string) => void
  onContextMenu: (event: ReactMouseEvent<HTMLElement>, path: string) => void
}): ReactElement {
  return (
    <div className="ds-workspace-editor-tabstrip flex shrink-0 items-center gap-1.5 border-b border-ds-border-muted/60">
      <div className="flex min-w-0 flex-1 items-center gap-1.5 overflow-x-auto">
        {tabs.length === 0 ? (
          <span className="px-2 py-1 text-[12px] text-ds-faint">{emptyLabel}</span>
        ) : (
          tabs.map((tab) => {
            const shown = tab.id === currentTabId
            const focused = shown && paneFocused
            const dirty = tab.content !== tab.savedContent
            const changed = Boolean(lookupPatchForPath(patchMap, tab.path))
            const editing = editingTabId === tab.id
            return (
              <span
                key={tab.id}
                className={`ds-workspace-editor-tab inline-flex max-w-[220px] shrink-0 items-center ${
                  focused
                    ? 'ds-workspace-editor-tab--active'
                    : shown
                      ? 'ds-workspace-editor-tab--open'
                      : ''
                }`}
                onContextMenu={(event) => onContextMenu(event, tab.path)}
              >
                <button
                  type="button"
                  onClick={() => onSelect(tab.id)}
                  className="inline-flex min-w-0 items-center truncate px-2 py-1 text-[12px]"
                  title={formatFilePathForDisplay(tab.path, workspaceRoot) ?? tab.path}
                >
                  <span className="truncate">{fileNameFromPath(tab.path)}</span>
                  <EditorTabMark
                    editing={editing}
                    dirty={dirty}
                    changed={changed}
                    loading={Boolean(tab.loading)}
                  />
                </button>
                <button
                  type="button"
                  onClick={() => onClose(tab.id)}
                  className="ds-workspace-editor-tab__close mr-0.5 inline-flex h-5 w-5 items-center justify-center rounded"
                  aria-label={closeLabel}
                >
                  <X className="h-3 w-3" strokeWidth={2} />
                </button>
              </span>
            )
          })
        )}
      </div>
      {trailing}
    </div>
  )
}

function PaneTabActions({
  tab,
  isEditing,
  onFind,
  onStartEdit,
  onCancelEdit,
  onSave,
  onCloseSplit
}: {
  tab: EditorTab | null
  isEditing: boolean
  onFind: () => void
  onStartEdit: () => void
  onCancelEdit: () => void
  onSave: () => void
  onCloseSplit?: () => void
}): ReactElement | null {
  const { t } = useTranslation('common')
  const canEditFile = Boolean(tab && tab.kind !== 'image')
  if (!canEditFile && !onCloseSplit) return null

  return (
    <div className="flex shrink-0 items-center gap-0.5 pl-1">
      {canEditFile && tab ? (
        <>
          <button
            type="button"
            onClick={onFind}
            disabled={tab.loading}
            className="inline-flex h-7 w-7 items-center justify-center rounded-md text-ds-muted transition hover:bg-ds-hover/60 hover:text-ds-ink disabled:opacity-45"
            aria-label={t('workspaceEditorFind')}
            title={t('workspaceEditorFind')}
          >
            <Search className="h-3.5 w-3.5" strokeWidth={1.85} />
          </button>
          {!isEditing ? (
            <button
              type="button"
              onClick={onStartEdit}
              disabled={tab.loading || tab.truncated}
              className="inline-flex h-7 w-7 items-center justify-center rounded-md text-ds-muted transition hover:bg-ds-hover/60 hover:text-ds-ink disabled:opacity-45"
              aria-label={t('workspaceEditorEdit')}
              title={
                tab.truncated ? t('workspaceEditorTruncated') : t('workspaceEditorEdit')
              }
            >
              <Pencil className="h-3.5 w-3.5" strokeWidth={1.85} />
            </button>
          ) : (
            <>
              <button
                type="button"
                onClick={onCancelEdit}
                className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[12px] text-ds-muted transition hover:bg-ds-hover/60 hover:text-ds-ink"
              >
                {t('workspaceEditorCancelEdit')}
              </button>
              <button
                type="button"
                onClick={onSave}
                disabled={tab.loading || tab.content === tab.savedContent}
                className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[12px] text-ds-muted transition hover:bg-ds-hover/60 hover:text-ds-ink disabled:opacity-45"
              >
                <Save className="h-3.5 w-3.5" strokeWidth={1.85} />
                {t('workspaceEditorSave')}
              </button>
            </>
          )}
        </>
      ) : null}
      {onCloseSplit ? (
        <span className="ml-1 flex items-center border-l border-[color-mix(in_srgb,var(--ds-text)_12%,transparent)] pl-1">
          <button
            type="button"
            onClick={onCloseSplit}
            className="inline-flex h-7 w-7 items-center justify-center rounded-md text-ds-muted transition hover:bg-ds-hover/60 hover:text-ds-ink"
            aria-label={t('workspaceEditorCloseSplit')}
            title={t('workspaceEditorCloseSplit')}
          >
            <Columns2 className="h-3.5 w-3.5" strokeWidth={1.85} />
          </button>
        </span>
      ) : null}
    </div>
  )
}

type EditorPaneHandle = {
  openFind: () => void
  getSelectionRange: () => { startLine: number; endLine: number } | null
}

const EditorPaneView = forwardRef<
  EditorPaneHandle,
  {
    tab: EditorTab | null
    workspaceRoot: string
    patch?: string
    isEditing: boolean
    focused: boolean
    /** Only when split — avoid stacking a left ring against the tree separator. */
    showFocusChrome: boolean
    externalOpenError: string | null
    onFocus: () => void
    onChange: (content: string) => void
  }
>(function EditorPaneView(
  {
    tab,
    workspaceRoot,
    patch,
    isEditing,
    focused,
    showFocusChrome,
    externalOpenError,
    onFocus,
    onChange
  },
  ref
): ReactElement {
  const { t } = useTranslation('common')
  const surfaceRef = useRef<WorkspaceEditorSurfaceHandle | null>(null)
  const [sourceFindOpen, setSourceFindOpen] = useState(false)
  const isImageTab = tab?.kind === 'image'
  const isHtmlPreview =
    Boolean(tab) && !isImageTab && isHtmlPreviewPath(tab!.path) && !isEditing && !sourceFindOpen
  const isMarkdownPreview =
    Boolean(tab) &&
    !isImageTab &&
    !isHtmlPreview &&
    isMarkdownPath(tab!.path) &&
    !isEditing &&
    !sourceFindOpen
  const showMonaco = Boolean(tab) && !isImageTab && !isHtmlPreview && !isMarkdownPreview

  const openFind = useCallback((): void => {
    if (!tab || isImageTab || tab.loading) return
    onFocus()
    if (
      (isMarkdownPath(tab.path) || isHtmlPreviewPath(tab.path)) &&
      !isEditing &&
      !sourceFindOpen
    ) {
      setSourceFindOpen(true)
      return
    }
    surfaceRef.current?.openFind()
  }, [tab, isImageTab, isEditing, sourceFindOpen, onFocus])

  useImperativeHandle(
    ref,
    () => ({
      openFind,
      getSelectionRange: () => surfaceRef.current?.getSelectionRange() ?? null
    }),
    [openFind]
  )

  useEffect(() => {
    setSourceFindOpen(false)
  }, [tab?.id])

  useEffect(() => {
    if (isEditing) setSourceFindOpen(false)
  }, [isEditing])

  useEffect(() => {
    if (!focused || !tab || isImageTab) return
    const onKeyDown = (event: KeyboardEvent): void => {
      if (!(event.metaKey || event.ctrlKey) || event.altKey || event.shiftKey) return
      if (event.key.toLowerCase() !== 'f') return
      const target = event.target
      if (
        target instanceof HTMLElement &&
        target.closest('input, textarea, select, [contenteditable="true"]') &&
        !target.closest('.monaco-editor')
      ) {
        return
      }
      event.preventDefault()
      event.stopPropagation()
      openFind()
    }
    window.addEventListener('keydown', onKeyDown, true)
    return () => window.removeEventListener('keydown', onKeyDown, true)
  }, [focused, tab, isImageTab, openFind])

  if (!tab) {
    return (
      <div className="flex min-h-0 min-w-0 flex-1 flex-col bg-ds-sidebar" onMouseDown={onFocus}>
        <div className="flex flex-1 items-center justify-center px-6 text-center text-[13px] text-ds-faint">
          {t('workspaceEditorSplitEmpty')}
        </div>
      </div>
    )
  }

  return (
    <div
      className={`flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-ds-sidebar ${
        showFocusChrome && focused
          ? 'shadow-[inset_0_0_0_1px_color-mix(in_srgb,var(--ds-text)_12%,transparent)]'
          : ''
      }`}
      onMouseDown={onFocus}
    >
      {externalOpenError && focused ? (
        <div className="shrink-0 border-b border-amber-200/70 bg-amber-50/80 px-3 py-2 text-[12px] text-amber-900 dark:border-amber-700/40 dark:bg-amber-950/30 dark:text-amber-100">
          {t('workspaceEditorOpenExternalFailed', { message: externalOpenError })}
        </div>
      ) : null}
      {tab.error ? (
        <div className="shrink-0 border-b border-amber-200/70 bg-amber-50/80 px-3 py-2 text-[12px] text-amber-900 dark:border-amber-700/40 dark:bg-amber-950/30 dark:text-amber-100">
          {tab.error}
        </div>
      ) : tab.truncated ? (
        <div className="shrink-0 border-b border-amber-200/70 bg-amber-50/80 px-3 py-2 text-[12px] text-amber-900 dark:border-amber-700/40 dark:bg-amber-950/30 dark:text-amber-100">
          {t('workspaceEditorTruncated')}
        </div>
      ) : null}
      {tab.loading ? (
        <EditorSurfaceFallback />
      ) : isImageTab ? (
        <ImageDocumentPreview path={tab.path} workspaceRoot={workspaceRoot} />
      ) : isHtmlPreview ? (
        <HtmlDocumentPreview path={tab.path} workspaceRoot={workspaceRoot} />
      ) : isMarkdownPreview ? (
        <MarkdownDocumentPreview content={tab.content} />
      ) : showMonaco ? (
        <Suspense fallback={<EditorSurfaceFallback />}>
          <LazyWorkspaceEditorSurface
            ref={surfaceRef}
            tab={tab}
            patch={patch}
            readOnly={!isEditing || Boolean(tab.truncated)}
            onChange={onChange}
            openFindOnReady={sourceFindOpen}
            onQuoteSelection={(startLine, endLine) => {
              const relative = copyableRelativePath(tab.path, workspaceRoot) || tab.path
              insertComposerSnippet(formatComposerPathMention(relative, startLine, endLine))
            }}
          />
        </Suspense>
      ) : null}
    </div>
  )
})

export function WorkspaceEditorPanel({
  workspaceRoot,
  blocks,
  hideTree = false
}: Props): ReactElement {
  const { t } = useTranslation('common')
  const trimmedRoot = workspaceRoot.trim()
  const tabs = useWorkspaceEditorStore((s) => s.tabs)
  const activeTabId = useWorkspaceEditorStore((s) => s.activeTabId)
  const secondaryTabId = useWorkspaceEditorStore((s) => s.secondaryTabId)
  const primaryTabIds = useWorkspaceEditorStore((s) =>
    s.primaryTabIds.length === 0 && s.tabs.length > 0
      ? s.tabs.map((tab) => tab.id)
      : s.primaryTabIds
  )
  const secondaryTabIds = useWorkspaceEditorStore((s) =>
    s.splitEnabled && s.secondaryTabIds.length === 0 && s.secondaryTabId
      ? [s.secondaryTabId]
      : s.secondaryTabIds
  )
  const focusedPane = useWorkspaceEditorStore((s) => s.focusedPane)
  const splitEnabled = useWorkspaceEditorStore((s) => s.splitEnabled)
  const openFile = useWorkspaceEditorStore((s) => s.openFile)
  const closeTab = useWorkspaceEditorStore((s) => s.closeTab)
  const setActiveTab = useWorkspaceEditorStore((s) => s.setActiveTab)
  const setFocusedPane = useWorkspaceEditorStore((s) => s.setFocusedPane)
  const closeSplit = useWorkspaceEditorStore((s) => s.closeSplit)
  const updateTabContent = useWorkspaceEditorStore((s) => s.updateTabContent)
  const revertTab = useWorkspaceEditorStore((s) => s.revertTab)
  const saveTab = useWorkspaceEditorStore((s) => s.saveTab)
  const resetForWorkspace = useWorkspaceEditorStore((s) => s.resetForWorkspace)
  const { result: gitChanges, reload: reloadGitChanges } = useGitWorkingChanges(trimmedRoot)
  const workspaceDirtyTick = useChatStore((s) => s.workspaceDirtyTick)
  useWorkspaceDirtyGitRefresh(workspaceDirtyTick, reloadGitChanges)
  const reloadCleanTabs = useWorkspaceEditorStore((s) => s.reloadCleanTabs)
  // The tick also bumps on plain agent file writes, so refreshing clean open
  // tabs here keeps them in sync with tool edits and rewind restores alike.
  const reloadCleanEditorTabs = useCallback(
    () => reloadCleanTabs(trimmedRoot),
    [reloadCleanTabs, trimmedRoot]
  )
  useWorkspaceDirtyGitRefresh(workspaceDirtyTick, reloadCleanEditorTabs)

  const [treeWidth, setTreeWidth] = useState(readStoredTreeWidth)
  const [splitRatio, setSplitRatio] = useState(readStoredSplitRatio)
  const [editingTabId, setEditingTabId] = useState<string | null>(null)
  const [externalOpenError, setExternalOpenError] = useState<string | null>(null)
  const [fileMenu, setFileMenu] = useState<FileMenuState | null>(null)
  const endPointerDragRef = useRef<(() => void) | null>(null)
  const splitHostRef = useRef<HTMLDivElement | null>(null)
  const primaryPaneRef = useRef<EditorPaneHandle | null>(null)
  const secondaryPaneRef = useRef<EditorPaneHandle | null>(null)

  useEffect(() => {
    return () => {
      endPointerDragRef.current?.()
    }
  }, [])

  const gitFiles = gitChanges?.ok ? gitChanges.files : null
  const changeSignature = useMemo(() => {
    const toolSig = blocks
      .filter(
        (block): block is typeof block & { id: string; status: string; detail?: string; filePath?: string } =>
          block.kind === 'tool' && block.toolKind === 'file_change'
      )
      .map((block) => `${block.id}|${block.status}|${block.filePath ?? ''}|${block.detail?.length ?? 0}`)
      .join('\n')
    const gitSig = gitFiles
      ? gitFiles.map((file) => `${file.path}|${file.status ?? ''}|${file.patch?.length ?? 0}`).join('\n')
      : ''
    return `${toolSig}\n---\n${gitSig}`
  }, [blocks, gitFiles])

  const patchMap = useMemo(
    () => buildWorkspaceChangePatchMap(blocks, gitFiles),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [changeSignature]
  )

  const primaryTabs = useMemo(
    () => orderTabsByIds(tabs, primaryTabIds),
    [tabs, primaryTabIds]
  )
  const secondaryTabs = useMemo(
    () => orderTabsByIds(tabs, secondaryTabIds),
    [tabs, secondaryTabIds]
  )
  const primaryTab = tabs.find((tab) => tab.id === activeTabId) ?? null
  const secondaryTab = tabs.find((tab) => tab.id === secondaryTabId) ?? null
  const focusedTab =
    splitEnabled && focusedPane === 'secondary' ? secondaryTab : primaryTab

  const dirtyPaths = useMemo(
    () =>
      new Set(
        tabs.filter((tab) => tab.content !== tab.savedContent).map((tab) => tab.id.replace(/\\/g, '/'))
      ),
    [tabs]
  )

  const activePaths = useMemo(() => {
    const paths: string[] = []
    if (primaryTab?.path) paths.push(primaryTab.path)
    if (splitEnabled && secondaryTab?.path) paths.push(secondaryTab.path)
    return paths
  }, [primaryTab?.path, secondaryTab?.path, splitEnabled])

  useEffect(() => {
    resetForWorkspace(trimmedRoot)
    setEditingTabId(null)
  }, [resetForWorkspace, trimmedRoot])

  useEffect(() => {
    setExternalOpenError(null)
  }, [focusedTab?.id])

  useEffect(() => {
    const onKey = (event: KeyboardEvent): void => {
      if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== 's') return
      if (event.altKey || event.shiftKey) return
      if (!isShortcutEnabled('saveFile')) return
      const target = event.target as HTMLElement | null
      if (!target?.closest('.ds-workspace-editor-pane')) return
      const tab = focusedTab
      if (!tab || tab.kind === 'image' || tab.truncated) return
      event.preventDefault()
      if (editingTabId !== tab.id) setEditingTabId(tab.id)
      if (tab.content !== tab.savedContent) void saveTab(tab.id, trimmedRoot)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [editingTabId, focusedTab, saveTab, trimmedRoot])

  const beginTreeResize = (event: ReactPointerEvent<HTMLDivElement>): void => {
    if (event.button !== 0) return
    event.preventDefault()
    endPointerDragRef.current?.()

    const startX = event.clientX
    const startWidth = treeWidth
    const prevCursor = document.body.style.cursor
    const prevUserSelect = document.body.style.userSelect
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'

    const onMove = (moveEvent: PointerEvent): void => {
      setTreeWidth(clampTreeWidth(startWidth + (moveEvent.clientX - startX)))
    }

    const endDrag = (): void => {
      document.body.style.cursor = prevCursor
      document.body.style.userSelect = prevUserSelect
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      endPointerDragRef.current = null
    }

    const onUp = (): void => {
      endDrag()
      setTreeWidth((current) => {
        try {
          window.localStorage.setItem(TREE_WIDTH_KEY, String(current))
        } catch {
          /* ignore */
        }
        return current
      })
    }

    endPointerDragRef.current = endDrag
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
  }

  const beginSplitResize = (event: ReactPointerEvent<HTMLDivElement>): void => {
    if (event.button !== 0) return
    event.preventDefault()
    endPointerDragRef.current?.()
    const host = splitHostRef.current
    if (!host) return

    const startX = event.clientX
    const startRatio = splitRatio
    const hostWidth = host.getBoundingClientRect().width
    const prevCursor = document.body.style.cursor
    const prevUserSelect = document.body.style.userSelect
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'

    const onMove = (moveEvent: PointerEvent): void => {
      if (hostWidth <= 0) return
      const next = startRatio + (moveEvent.clientX - startX) / hostWidth
      setSplitRatio(Math.min(SPLIT_MAX, Math.max(SPLIT_MIN, next)))
    }

    const endDrag = (): void => {
      document.body.style.cursor = prevCursor
      document.body.style.userSelect = prevUserSelect
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      endPointerDragRef.current = null
    }

    const onUp = (): void => {
      endDrag()
      setSplitRatio((current) => {
        try {
          window.localStorage.setItem(SPLIT_RATIO_KEY, String(current))
        } catch {
          /* ignore */
        }
        return current
      })
    }

    endPointerDragRef.current = endDrag
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
  }

  const handleCloseTab = useCallback(
    (tabId: string, pane?: EditorPaneId): void => {
      const tab = tabs.find((entry) => entry.id === tabId)
      const inPrimary = primaryTabIds.includes(tabId)
      const inSecondary = splitEnabled && secondaryTabIds.includes(tabId)
      const target =
        pane ??
        (focusedPane === 'secondary' && inSecondary
          ? 'secondary'
          : inPrimary
            ? 'primary'
            : inSecondary
              ? 'secondary'
              : 'primary')
      const otherPaneStillHas = target === 'primary' ? inSecondary : inPrimary
      if (tab && tab.content !== tab.savedContent && !otherPaneStillHas) {
        if (
          !window.confirm(
            t('workspaceEditorCloseDirtyConfirm', { file: fileNameFromPath(tab.path) })
          )
        ) {
          return
        }
      }
      if (editingTabId === tabId && !otherPaneStillHas) setEditingTabId(null)
      closeTab(tabId, pane ?? target)
    },
    [
      tabs,
      editingTabId,
      closeTab,
      t,
      splitEnabled,
      focusedPane,
      primaryTabIds,
      secondaryTabIds
    ]
  )

  useEffect(() => {
    const onCloseActive = (): void => {
      if (!focusedTab) return
      handleCloseTab(focusedTab.id, splitEnabled ? focusedPane : 'primary')
    }
    window.addEventListener(EDITOR_CLOSE_ACTIVE_TAB_EVENT, onCloseActive)
    return () => window.removeEventListener(EDITOR_CLOSE_ACTIVE_TAB_EVENT, onCloseActive)
  }, [focusedTab, focusedPane, handleCloseTab, splitEnabled])

  const cancelEditForTab = (tab: EditorTab | null): void => {
    if (!tab) {
      setEditingTabId(null)
      return
    }
    if (tab.content !== tab.savedContent) {
      if (!window.confirm(t('workspaceEditorDiscardConfirm'))) return
      revertTab(tab.id)
    }
    setEditingTabId(null)
  }

  const paneActions = (tab: EditorTab | null, pane: EditorPaneId): ReactElement | null => (
    <PaneTabActions
      tab={tab}
      isEditing={Boolean(tab && editingTabId === tab.id && !tab.truncated)}
      onFind={() =>
        (pane === 'secondary' ? secondaryPaneRef : primaryPaneRef).current?.openFind()
      }
      onStartEdit={() => {
        if (!tab || tab.truncated) return
        setFocusedPane(pane)
        setEditingTabId(tab.id)
      }}
      onCancelEdit={() => cancelEditForTab(tab)}
      onSave={() => {
        if (tab) void saveTab(tab.id, trimmedRoot)
      }}
      onCloseSplit={splitEnabled && pane === 'secondary' ? closeSplit : undefined}
    />
  )

  const openFileMenu = (event: ReactMouseEvent, path: string, pane?: EditorPaneId): void => {
    event.preventDefault()
    event.stopPropagation()
    setFileMenu({ x: event.clientX, y: event.clientY, path, pane })
  }

  const handleFileMenuAction = useCallback(
    (action: WorkspaceFileContextMenuAction): void => {
      if (!fileMenu) return
      const path = normalizeEditorPathForTab(fileMenu.path)
      if (!path) return
      const tab = tabs.find((entry) => entry.id === path) ?? null

      switch (action) {
        case 'open-with-editor':
          setExternalOpenError(null)
          void openWorkspacePathInEditor({ path }, trimmedRoot || undefined).then((result) => {
            if (!result.ok) setExternalOpenError(result.message)
          })
          break
        case 'edit':
          if (isImagePreviewPath(path) || tab?.truncated) break
          void openFile(path, trimmedRoot).then(() => setEditingTabId(path))
          break
        case 'split-right':
          void openFile(path, trimmedRoot, undefined, undefined, { toSide: true })
          break
        case 'close':
          if (tab) handleCloseTab(tab.id, fileMenu.pane)
          break
        case 'close-split':
          closeSplit()
          break
        case 'reveal-in-folder':
          void revealWorkspacePathInFolder(path)
          break
        case 'copy-path':
          void navigator.clipboard?.writeText(path)
          break
        case 'copy-relative-path':
          void navigator.clipboard?.writeText(
            copyableRelativePath(path, trimmedRoot || path)
          )
          break
        case 'quote-in-chat': {
          const relative = copyableRelativePath(path, trimmedRoot) || path
          insertComposerSnippet(formatComposerPathMention(relative))
          break
        }
      }
    },
    [fileMenu, tabs, trimmedRoot, openFile, closeSplit, handleCloseTab]
  )

  const selectTab = (tabId: string, pane?: EditorPaneId): void => {
    setActiveTab(tabId, pane)
  }

  const focusPane = (pane: EditorPaneId): void => {
    setFocusedPane(pane)
  }

  const tabStripShared = {
    patchMap,
    editingTabId,
    workspaceRoot: trimmedRoot,
    emptyLabel: t('workspaceEditorEmpty'),
    closeLabel: t('workspaceEditorCloseTab')
  }

  return (
    <div className="ds-workspace-editor-pane ds-no-drag flex h-full min-h-0 flex-col">
      <div className="relative flex h-full min-h-0 flex-1 bg-ds-sidebar">
        {hideTree ? null : (
          <div className="relative h-full min-h-0 shrink-0" style={{ width: treeWidth }}>
            {/* Expand state is cached per workspace root inside WorkspaceFileTree
                so switching IDE center tabs (changes/search) does not reset folds. */}
            <WorkspaceFileTree
              workspaceRoot={trimmedRoot}
              activePaths={activePaths}
              dirtyPaths={dirtyPaths}
              patchMap={patchMap}
              workspaceDirtyTick={workspaceDirtyTick}
              onOpenFile={(path) => {
                void openFile(path, trimmedRoot)
              }}
              onFileContextMenu={openFileMenu}
            />
            {/* Overlay handle — no layout gap, so tree/editor share one continuous fill. */}
            <div
              role="separator"
              aria-orientation="vertical"
              aria-label={t('workspaceEditorTreeResize')}
              className="ds-no-drag absolute inset-y-0 right-0 z-20 w-2 translate-x-1/2 cursor-col-resize"
              onPointerDown={beginTreeResize}
            />
          </div>
        )}

        <div className="flex h-full min-h-0 min-w-0 flex-1 flex-col bg-ds-sidebar">
          {!splitEnabled ? (
            <>
              <EditorTabStrip
                {...tabStripShared}
                tabs={primaryTabs}
                currentTabId={activeTabId}
                paneFocused
                trailing={paneActions(primaryTab, 'primary')}
                onSelect={(tabId) => selectTab(tabId)}
                onClose={(tabId) => handleCloseTab(tabId, 'primary')}
                onContextMenu={(event, path) => openFileMenu(event, path, 'primary')}
              />
              {focusedTab ? (
                <EditorBreadcrumb path={focusedTab.path} workspaceRoot={trimmedRoot} />
              ) : null}
            </>
          ) : null}

          {primaryTab || (splitEnabled && secondaryTab) ? (
            <div ref={splitHostRef} className="flex min-h-0 flex-1 overflow-hidden">
              <div
                className="flex min-h-0 min-w-0 flex-col overflow-hidden"
                style={splitEnabled ? { width: `${splitRatio * 100}%` } : { width: '100%' }}
              >
                {splitEnabled ? (
                  <>
                    <EditorTabStrip
                      {...tabStripShared}
                      tabs={primaryTabs}
                      currentTabId={primaryTab?.id ?? null}
                      paneFocused={focusedPane === 'primary'}
                      trailing={paneActions(primaryTab, 'primary')}
                      onSelect={(tabId) => selectTab(tabId, 'primary')}
                      onClose={(tabId) => handleCloseTab(tabId, 'primary')}
                      onContextMenu={(event, path) => openFileMenu(event, path, 'primary')}
                    />
                    {primaryTab ? (
                      <EditorBreadcrumb path={primaryTab.path} workspaceRoot={trimmedRoot} />
                    ) : null}
                  </>
                ) : null}
                <EditorPaneView
                  ref={primaryPaneRef}
                  tab={primaryTab}
                  workspaceRoot={trimmedRoot}
                  patch={
                    primaryTab ? lookupPatchForPath(patchMap, primaryTab.path) : undefined
                  }
                  isEditing={Boolean(
                    primaryTab && editingTabId === primaryTab.id && !primaryTab.truncated
                  )}
                  focused={!splitEnabled || focusedPane === 'primary'}
                  showFocusChrome={splitEnabled}
                  externalOpenError={externalOpenError}
                  onFocus={() => focusPane('primary')}
                  onChange={(content) => {
                    if (primaryTab) updateTabContent(primaryTab.id, content)
                  }}
                />
              </div>

              {splitEnabled ? (
                <>
                  <div className="relative w-px shrink-0 bg-[color-mix(in_srgb,var(--ds-text)_14%,transparent)]">
                    <div
                      role="separator"
                      aria-orientation="vertical"
                      aria-label={t('workspaceEditorSplitResize')}
                      className="ds-no-drag absolute inset-y-0 left-1/2 z-20 w-2 -translate-x-1/2 cursor-col-resize"
                      onPointerDown={beginSplitResize}
                    />
                  </div>
                  <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-ds-sidebar">
                    <EditorTabStrip
                      {...tabStripShared}
                      tabs={secondaryTabs}
                      currentTabId={secondaryTab?.id ?? null}
                      paneFocused={focusedPane === 'secondary'}
                      trailing={paneActions(secondaryTab, 'secondary')}
                      onSelect={(tabId) => selectTab(tabId, 'secondary')}
                      onClose={(tabId) => handleCloseTab(tabId, 'secondary')}
                      onContextMenu={(event, path) => openFileMenu(event, path, 'secondary')}
                    />
                    {secondaryTab ? (
                      <EditorBreadcrumb path={secondaryTab.path} workspaceRoot={trimmedRoot} />
                    ) : null}
                    <EditorPaneView
                      ref={secondaryPaneRef}
                      tab={secondaryTab}
                      workspaceRoot={trimmedRoot}
                      patch={
                        secondaryTab
                          ? lookupPatchForPath(patchMap, secondaryTab.path)
                          : undefined
                      }
                      isEditing={Boolean(
                        secondaryTab &&
                          editingTabId === secondaryTab.id &&
                          !secondaryTab.truncated
                      )}
                      focused={focusedPane === 'secondary'}
                      showFocusChrome={splitEnabled}
                      externalOpenError={externalOpenError}
                      onFocus={() => focusPane('secondary')}
                      onChange={(content) => {
                        if (secondaryTab) updateTabContent(secondaryTab.id, content)
                      }}
                    />
                  </div>
                </>
              ) : null}
            </div>
          ) : (
            <div className="flex flex-1 items-center justify-center px-6 text-center text-[13px] text-ds-faint">
              {t('workspaceEditorPickFile')}
            </div>
          )}
        </div>
      </div>

      {fileMenu ? (
        <WorkspaceFileContextMenu
          x={fileMenu.x}
          y={fileMenu.y}
          canEdit={!isImagePreviewPath(normalizeEditorPathForTab(fileMenu.path))}
          canClose={tabs.some((entry) => entry.id === normalizeEditorPathForTab(fileMenu.path))}
          canSplitRight
          canCloseSplit={splitEnabled}
          onAction={handleFileMenuAction}
          onClose={() => setFileMenu(null)}
          t={t}
        />
      ) : null}
    </div>
  )
}
