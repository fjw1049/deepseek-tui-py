import type { PointerEvent as ReactPointerEvent, ReactElement } from 'react'
import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { Loader2, Pencil, Save, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { ChatBlock } from '../../agent/types'
import { formatFilePathForDisplay } from '../../lib/diff-stats'
import { useGitWorkingChanges } from '../../hooks/use-git-working-changes'
import {
  buildWorkspaceChangePatchMap,
  lookupPatchForPath
} from '../../lib/workspace-change-patches'
import { useWorkspaceEditorStore } from '../../store/workspace-editor-store'
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
const TREE_DEFAULT = 176
const TREE_MIN = 120
const TREE_MAX = 420

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

export function WorkspaceEditorPanel({ workspaceRoot, blocks }: Props): ReactElement {
  const { t } = useTranslation('common')
  const trimmedRoot = workspaceRoot.trim()
  const tabs = useWorkspaceEditorStore((s) => s.tabs)
  const activeTabId = useWorkspaceEditorStore((s) => s.activeTabId)
  const openFile = useWorkspaceEditorStore((s) => s.openFile)
  const closeTab = useWorkspaceEditorStore((s) => s.closeTab)
  const setActiveTab = useWorkspaceEditorStore((s) => s.setActiveTab)
  const updateTabContent = useWorkspaceEditorStore((s) => s.updateTabContent)
  const saveActiveTab = useWorkspaceEditorStore((s) => s.saveActiveTab)
  const resetForWorkspace = useWorkspaceEditorStore((s) => s.resetForWorkspace)
  const { result: gitChanges } = useGitWorkingChanges(trimmedRoot)

  const [treeWidth, setTreeWidth] = useState(readStoredTreeWidth)
  const [editingTabId, setEditingTabId] = useState<string | null>(null)
  const endPointerDragRef = useRef<(() => void) | null>(null)

  useEffect(() => {
    return () => {
      endPointerDragRef.current?.()
    }
  }, [])

  // Rebuild patchMap only when the actual set of file_change tool blocks or
  // git working changes shifts — not on every streaming delta (which swaps
  // the blocks array identity ~60x/s and would otherwise rebuild the Map each
  // frame while the editor sits idle).
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

  const activeTab = tabs.find((tab) => tab.id === activeTabId) ?? null
  const activePatch = activeTab ? lookupPatchForPath(patchMap, activeTab.path) : undefined
  const isEditing = Boolean(activeTab && editingTabId === activeTab.id)
  const dirtyPaths = useMemo(
    () =>
      new Set(
        tabs.filter((tab) => tab.content !== tab.savedContent).map((tab) => tab.id.replace(/\\/g, '/'))
      ),
    [tabs]
  )

  useEffect(() => {
    resetForWorkspace(trimmedRoot)
    setEditingTabId(null)
  }, [resetForWorkspace, trimmedRoot])

  useEffect(() => {
    setEditingTabId(null)
  }, [activeTabId])

  useEffect(() => {
    if (!isEditing) return
    const onKey = (event: KeyboardEvent): void => {
      if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== 's') return
      const target = event.target as HTMLElement | null
      if (!target?.closest('.ds-workspace-editor-pane')) return
      event.preventDefault()
      void saveActiveTab(trimmedRoot)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [isEditing, saveActiveTab, trimmedRoot])

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

  const handleCloseTab = (tabId: string): void => {
    if (editingTabId === tabId) setEditingTabId(null)
    closeTab(tabId)
  }

  return (
    <div className="ds-workspace-editor-pane ds-no-drag flex h-full min-h-0 flex-col">
      <div className="relative flex h-full min-h-0 flex-1">
        <div className="h-full min-h-0 shrink-0" style={{ width: treeWidth }}>
          <WorkspaceFileTree
            workspaceRoot={trimmedRoot}
            dirtyPaths={dirtyPaths}
            patchMap={patchMap}
            onOpenFile={(path) => {
              void openFile(path, trimmedRoot)
            }}
          />
        </div>

        <div
          role="separator"
          aria-orientation="vertical"
          aria-label={t('workspaceEditorTreeResize')}
          className="ds-no-drag relative z-20 w-1.5 shrink-0 cursor-col-resize after:absolute after:inset-y-0 after:left-1/2 after:w-px after:-translate-x-1/2 after:bg-[color-mix(in_srgb,var(--ds-text)_14%,transparent)] after:transition-colors after:duration-200 hover:after:bg-[color-mix(in_srgb,var(--ds-text)_24%,transparent)] active:after:bg-[color-mix(in_srgb,var(--ds-text)_24%,transparent)]"
          onPointerDown={beginTreeResize}
        />

        <div className="flex h-full min-h-0 min-w-0 flex-1 flex-col">
          <div className="flex shrink-0 items-center gap-1 overflow-x-auto border-b border-ds-border-muted/60 px-1 py-1">
            {tabs.length === 0 ? (
              <span className="px-2 py-1 text-[12px] text-ds-faint">{t('workspaceEditorEmpty')}</span>
            ) : (
              tabs.map((tab) => {
                const active = tab.id === activeTabId
                const dirty = tab.content !== tab.savedContent
                const changed = Boolean(lookupPatchForPath(patchMap, tab.path))
                const editing = editingTabId === tab.id
                return (
                  <span
                    key={tab.id}
                    className={`inline-flex max-w-[220px] shrink-0 items-center rounded-md border ${
                      active
                        ? 'border-ds-border-muted bg-ds-hover/50 text-ds-ink'
                        : 'border-transparent text-ds-muted hover:bg-ds-hover/40'
                    }`}
                  >
                    <button
                      type="button"
                      onClick={() => setActiveTab(tab.id)}
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

          {activeTab ? (
            <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
              <div className="flex shrink-0 items-center justify-between gap-2 border-b border-ds-border-muted/40 px-3 py-1.5">
                <span className="truncate text-[12px] text-ds-faint">
                  {formatFilePathForDisplay(activeTab.path, trimmedRoot) ?? activeTab.path}
                </span>
                <div className="flex shrink-0 items-center gap-1">
                  {isEditing ? (
                    <>
                      <button
                        type="button"
                        onClick={() => setEditingTabId(null)}
                        className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[12px] text-ds-muted transition hover:bg-ds-hover/60 hover:text-ds-ink"
                      >
                        {t('workspaceEditorCancelEdit')}
                      </button>
                      <button
                        type="button"
                        onClick={() => void saveActiveTab(trimmedRoot)}
                        disabled={activeTab.loading || activeTab.content === activeTab.savedContent}
                        className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[12px] text-ds-muted transition hover:bg-ds-hover/60 hover:text-ds-ink disabled:opacity-45"
                      >
                        <Save className="h-3.5 w-3.5" strokeWidth={1.85} />
                        {t('workspaceEditorSave')}
                      </button>
                    </>
                  ) : (
                    <button
                      type="button"
                      onClick={() => setEditingTabId(activeTab.id)}
                      disabled={activeTab.loading}
                      className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[12px] text-ds-muted transition hover:bg-ds-hover/60 hover:text-ds-ink disabled:opacity-45"
                    >
                      <Pencil className="h-3.5 w-3.5" strokeWidth={1.85} />
                      {t('workspaceEditorEdit')}
                    </button>
                  )}
                </div>
              </div>
              {activeTab.error ? (
                <div className="shrink-0 border-b border-amber-200/70 bg-amber-50/80 px-3 py-2 text-[12px] text-amber-900 dark:border-amber-700/40 dark:bg-amber-950/30 dark:text-amber-100">
                  {activeTab.error}
                </div>
              ) : null}
              {activeTab.loading ? (
                <EditorSurfaceFallback />
              ) : (
                <Suspense fallback={<EditorSurfaceFallback />}>
                  <LazyWorkspaceEditorSurface
                    tab={activeTab}
                    patch={activePatch}
                    readOnly={!isEditing}
                    onChange={(content) => updateTabContent(activeTab.id, content)}
                  />
                </Suspense>
              )}
            </div>
          ) : (
            <div className="flex flex-1 items-center justify-center px-6 text-center text-[13px] text-ds-faint">
              {t('workspaceEditorPickFile')}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
