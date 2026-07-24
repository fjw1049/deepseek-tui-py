import type { MouseEvent as ReactMouseEvent, PointerEvent as ReactPointerEvent, ReactElement } from 'react'
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Loader2, Pencil, Save, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { isImagePreviewPath } from '@shared/image-preview'
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
  buildWorkspaceChangePatchMap,
  lookupPatchForPath
} from '../../lib/workspace-change-patches'
import {
  normalizeEditorPathForTab,
  useWorkspaceEditorStore,
  type EditorPaneId,
  type EditorTab
} from '../../store/workspace-editor-store'
import { ImageDocumentPreview } from './ImageDocumentPreview'
import { MarkdownDocumentPreview } from './MarkdownDocumentPreview'
import {
  WorkspaceFileContextMenu,
  type WorkspaceFileContextMenuAction
} from './WorkspaceFileContextMenu'
import { WorkspaceFileTree } from './WorkspaceFileTree'

const LazyWorkspaceEditorSurface = lazy(() =>
  import('./WorkspaceEditorSurface').then((module) => ({
    default: module.WorkspaceEditorSurface
  }))
)

type Props = {
  workspaceRoot: string
  blocks: ChatBlock[]
}

const TREE_WIDTH_KEY = 'deepseekgui.layout.workspaceEditorTreeWidth'
const SPLIT_RATIO_KEY = 'deepseekgui.layout.workspaceEditorSplitRatio'
const TREE_DEFAULT = 176
const TREE_MIN = 120
const TREE_MAX = 420
const SPLIT_DEFAULT = 0.5
const SPLIT_MIN = 0.25
const SPLIT_MAX = 0.75

type FileMenuState = {
  x: number
  y: number
  path: string
}

function readStoredTreeWidth(): number {
  try {
    const raw = window.localStorage.getItem(TREE_WIDTH_KEY)
    if (!raw) return TREE_DEFAULT
    const parsed = Number(raw)
    if (!Number.isFinite(parsed)) return TREE_DEFAULT
    return Math.round(parsed)
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
    <div className="flex min-h-0 flex-1 items-center justify-center bg-ds-sidebar">
      <Loader2 className="h-5 w-5 animate-spin text-ds-faint" strokeWidth={1.8} />
    </div>
  )
}

function EditorPaneView({
  tab,
  workspaceRoot,
  patch,
  isEditing,
  focused,
  showFocusChrome,
  externalOpenError,
  onFocus,
  onEdit,
  onSave,
  onCancelEdit,
  onChange
}: {
  tab: EditorTab | null
  workspaceRoot: string
  patch?: string
  isEditing: boolean
  focused: boolean
  /** Only when split — avoid stacking a left ring against the tree separator. */
  showFocusChrome: boolean
  externalOpenError: string | null
  onFocus: () => void
  onEdit: () => void
  onSave: () => void
  onCancelEdit: () => void
  onChange: (content: string) => void
}): ReactElement {
  const { t } = useTranslation('common')
  const isImageTab = tab?.kind === 'image'

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
      <div className="flex shrink-0 items-center justify-between gap-2 border-b border-ds-border-muted/40 px-3 py-1.5">
        <span className="truncate text-[12px] text-ds-faint">
          {formatFilePathForDisplay(tab.path, workspaceRoot) ?? tab.path}
        </span>
        <div className="flex shrink-0 items-center gap-1">
          {!isImageTab && !isEditing ? (
            <button
              type="button"
              onClick={onEdit}
              disabled={tab.loading}
              className="inline-flex h-7 w-7 items-center justify-center rounded-md text-ds-muted transition hover:bg-ds-hover/60 hover:text-ds-ink disabled:opacity-45"
              aria-label={t('workspaceEditorEdit')}
              title={t('workspaceEditorEdit')}
            >
              <Pencil className="h-3.5 w-3.5" strokeWidth={1.85} />
            </button>
          ) : null}
          {isEditing ? (
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
          ) : null}
        </div>
      </div>
      {externalOpenError && focused ? (
        <div className="shrink-0 border-b border-amber-200/70 bg-amber-50/80 px-3 py-2 text-[12px] text-amber-900 dark:border-amber-700/40 dark:bg-amber-950/30 dark:text-amber-100">
          {t('workspaceEditorOpenExternalFailed', { message: externalOpenError })}
        </div>
      ) : null}
      {tab.error ? (
        <div className="shrink-0 border-b border-amber-200/70 bg-amber-50/80 px-3 py-2 text-[12px] text-amber-900 dark:border-amber-700/40 dark:bg-amber-950/30 dark:text-amber-100">
          {tab.error}
        </div>
      ) : null}
      {tab.loading ? (
        <EditorSurfaceFallback />
      ) : isImageTab ? (
        <ImageDocumentPreview path={tab.path} workspaceRoot={workspaceRoot} />
      ) : isMarkdownPath(tab.path) && !isEditing ? (
        <MarkdownDocumentPreview content={tab.content} />
      ) : (
        <Suspense fallback={<EditorSurfaceFallback />}>
          <LazyWorkspaceEditorSurface
            tab={tab}
            patch={patch}
            readOnly={!isEditing}
            onChange={onChange}
          />
        </Suspense>
      )}
    </div>
  )
}

export function WorkspaceEditorPanel({ workspaceRoot, blocks }: Props): ReactElement {
  const { t } = useTranslation('common')
  const trimmedRoot = workspaceRoot.trim()
  const tabs = useWorkspaceEditorStore((s) => s.tabs)
  const activeTabId = useWorkspaceEditorStore((s) => s.activeTabId)
  const secondaryTabId = useWorkspaceEditorStore((s) => s.secondaryTabId)
  const focusedPane = useWorkspaceEditorStore((s) => s.focusedPane)
  const splitEnabled = useWorkspaceEditorStore((s) => s.splitEnabled)
  const openFile = useWorkspaceEditorStore((s) => s.openFile)
  const closeTab = useWorkspaceEditorStore((s) => s.closeTab)
  const setActiveTab = useWorkspaceEditorStore((s) => s.setActiveTab)
  const setFocusedPane = useWorkspaceEditorStore((s) => s.setFocusedPane)
  const closeSplit = useWorkspaceEditorStore((s) => s.closeSplit)
  const updateTabContent = useWorkspaceEditorStore((s) => s.updateTabContent)
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
    if (!editingTabId) return
    const onKey = (event: KeyboardEvent): void => {
      if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== 's') return
      const target = event.target as HTMLElement | null
      if (!target?.closest('.ds-workspace-editor-pane')) return
      event.preventDefault()
      void saveTab(editingTabId, trimmedRoot)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [editingTabId, saveTab, trimmedRoot])

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

  const handleCloseTab = (tabId: string): void => {
    if (editingTabId === tabId) setEditingTabId(null)
    closeTab(tabId)
  }

  const openFileMenu = (event: ReactMouseEvent, path: string): void => {
    event.preventDefault()
    event.stopPropagation()
    setFileMenu({ x: event.clientX, y: event.clientY, path })
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
          if (isImagePreviewPath(path)) break
          void openFile(path, trimmedRoot).then(() => setEditingTabId(path))
          break
        case 'split-right':
          void openFile(path, trimmedRoot, undefined, undefined, { toSide: true })
          break
        case 'close':
          if (tab) {
            if (editingTabId === tab.id) setEditingTabId(null)
            closeTab(tab.id)
          }
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
      }
    },
    [fileMenu, tabs, trimmedRoot, openFile, closeTab, closeSplit, editingTabId]
  )

  const selectTab = (tabId: string): void => {
    setActiveTab(tabId)
  }

  const focusPane = (pane: EditorPaneId): void => {
    setFocusedPane(pane)
  }

  return (
    <div className="ds-workspace-editor-pane ds-no-drag flex h-full min-h-0 flex-col">
      <div className="relative flex h-full min-h-0 flex-1 bg-ds-sidebar">
        <div className="relative h-full min-h-0 shrink-0" style={{ width: treeWidth }}>
          <WorkspaceFileTree
            workspaceRoot={trimmedRoot}
            activePaths={activePaths}
            dirtyPaths={dirtyPaths}
            patchMap={patchMap}
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

        <div className="flex h-full min-h-0 min-w-0 flex-1 flex-col bg-ds-sidebar">
          <div className="flex shrink-0 items-center gap-1.5 overflow-x-auto border-b border-ds-border-muted/60 px-1.5 py-1.5">
            {tabs.length === 0 ? (
              <span className="px-2 py-1 text-[12px] text-ds-faint">{t('workspaceEditorEmpty')}</span>
            ) : (
              tabs.map((tab) => {
                const inPrimary = tab.id === activeTabId
                const inSecondary = splitEnabled && tab.id === secondaryTabId
                const shown = inPrimary || inSecondary
                const focused =
                  (focusedPane === 'primary' && inPrimary) ||
                  (focusedPane === 'secondary' && inSecondary)
                const dirty = tab.content !== tab.savedContent
                const changed = Boolean(lookupPatchForPath(patchMap, tab.path))
                const editing = editingTabId === tab.id
                return (
                  <span
                    key={tab.id}
                    className={`inline-flex max-w-[220px] shrink-0 items-center rounded-md border ${
                      focused
                        ? 'border-[color-mix(in_srgb,var(--ds-text)_28%,transparent)] bg-ds-hover/55 text-ds-ink'
                        : shown
                          ? 'border-[color-mix(in_srgb,var(--ds-text)_18%,transparent)] bg-ds-hover/30 text-ds-ink'
                          : 'border-[color-mix(in_srgb,var(--ds-text)_14%,transparent)] bg-[color-mix(in_srgb,var(--ds-text)_4%,transparent)] text-ds-muted hover:border-[color-mix(in_srgb,var(--ds-text)_22%,transparent)] hover:bg-ds-hover/40 hover:text-ds-ink'
                    }`}
                    onContextMenu={(event) => openFileMenu(event, tab.path)}
                  >
                    <button
                      type="button"
                      onClick={() => selectTab(tab.id)}
                      className="truncate px-2 py-1 text-[12px]"
                      title={formatFilePathForDisplay(tab.path, trimmedRoot) ?? tab.path}
                    >
                      {fileNameFromPath(tab.path)}
                      {editing ? ' ✎' : dirty ? ' ●' : changed ? ' ◦' : ''}
                      {tab.loading ? ' …' : ''}
                    </button>
                    <button
                      type="button"
                      onClick={() => handleCloseTab(tab.id)}
                      className="mr-0.5 inline-flex h-5 w-5 items-center justify-center rounded text-ds-faint hover:bg-ds-hover/70 hover:text-ds-ink"
                      aria-label={t('workspaceEditorCloseTab')}
                    >
                      <X className="h-3 w-3" strokeWidth={2} />
                    </button>
                  </span>
                )
              })
            )}
          </div>

          {primaryTab || (splitEnabled && secondaryTab) ? (
            <div ref={splitHostRef} className="flex min-h-0 flex-1 overflow-hidden">
              <div
                className="flex min-h-0 min-w-0 flex-col overflow-hidden"
                style={splitEnabled ? { width: `${splitRatio * 100}%` } : { width: '100%' }}
              >
                <EditorPaneView
                  tab={primaryTab}
                  workspaceRoot={trimmedRoot}
                  patch={
                    primaryTab ? lookupPatchForPath(patchMap, primaryTab.path) : undefined
                  }
                  isEditing={Boolean(primaryTab && editingTabId === primaryTab.id)}
                  focused={!splitEnabled || focusedPane === 'primary'}
                  showFocusChrome={splitEnabled}
                  externalOpenError={externalOpenError}
                  onFocus={() => focusPane('primary')}
                  onEdit={() => {
                    if (primaryTab) setEditingTabId(primaryTab.id)
                  }}
                  onSave={() => {
                    if (primaryTab) void saveTab(primaryTab.id, trimmedRoot)
                  }}
                  onCancelEdit={() => setEditingTabId(null)}
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
                    <EditorPaneView
                      tab={secondaryTab}
                      workspaceRoot={trimmedRoot}
                      patch={
                        secondaryTab
                          ? lookupPatchForPath(patchMap, secondaryTab.path)
                          : undefined
                      }
                      isEditing={Boolean(secondaryTab && editingTabId === secondaryTab.id)}
                      focused={focusedPane === 'secondary'}
                      showFocusChrome={splitEnabled}
                      externalOpenError={externalOpenError}
                      onFocus={() => focusPane('secondary')}
                      onEdit={() => {
                        if (secondaryTab) setEditingTabId(secondaryTab.id)
                      }}
                      onSave={() => {
                        if (secondaryTab) void saveTab(secondaryTab.id, trimmedRoot)
                      }}
                      onCancelEdit={() => setEditingTabId(null)}
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
