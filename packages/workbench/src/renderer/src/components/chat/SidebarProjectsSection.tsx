import type { MouseEvent as ReactMouseEvent, ReactElement } from 'react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Archive,
  Check,
  CheckSquare,
  ChevronDown,
  ChevronRight,
  Clock,
  Folder,
  FolderClosed,
  FolderOpen,
  GitBranch,
  LayoutGrid,
  Loader2,
  MessageSquare,
  MoreHorizontal,
  Pin,
  PinOff,
  Plus,
  Square,
  Trash2,
  X
} from 'lucide-react'
import type { NormalizedThread } from '../../agent/types'
import { useThreadsWithActiveTasks } from '../../hooks/use-thread-tasks'
import { extractTasksFromBlocks } from '../../lib/extract-tasks-from-blocks'
import { useChatStore } from '../../store/chat-store'
import { formatRelativeTimeLargestUnit } from '../../lib/format-relative-time'
import { workspaceLabelFromPath } from '../../lib/workspace-label'
import { parseUserFocusPrefix } from '../../lib/user-focus-prefix'
import {
  copyableRelativePath,
  isWorkspaceHidden,
  sidebarLabelSwatch,
  threadLabelKey,
  workspaceLabelKey,
  type SidebarLabelColor
} from '../../lib/sidebar-chrome'
import { openWorkspacePathInEditor, revealWorkspacePathInFolder } from '../../lib/open-workspace-path'
import {
  isChatsWorkspace,
  isClawWorkspacePath,
  isInternalTemporaryWorkspace,
  normalizeWorkspaceRoot
} from '../../lib/workspace-path'
import { ProjectContextMenu, type ProjectContextMenuAction } from './ProjectContextMenu'
import { ThreadContextMenu, type ThreadContextMenuAction } from './ThreadContextMenu'
import { HoverInfoCard } from './ThreadHoverCard'

type SidebarProjectsSectionProps = {
  threads: NormalizedThread[]
  activeThreadId: string | null
  runtimeReady: boolean
  workspaceRoot: string
  busy: boolean
  watchTurnCompletion: Record<string, boolean>
  unreadThreadIds: Record<string, boolean>
  pinnedThreadIds: string[]
  locale: string
  selectionMode?: boolean
  selectedIds?: Set<string>
  onToggleSelect?: (threadId: string) => void
  onTogglePin: (threadId: string) => void
  onPickWorkspace: () => void
  onRemoveWorkspace: (workspacePath: string) => Promise<void>
  onDeleteWorkspace: (workspacePath: string) => Promise<void>
  onCreateThreadInWorkspace: (workspacePath: string) => void
  onSelectThread: (threadId: string) => void
  onOpenThreadTerminal: (threadId: string) => Promise<void>
  onDeleteThread: (threadId: string) => Promise<void>
  onCompactThread: (threadId: string) => Promise<void>
  t: (k: string, opts?: Record<string, unknown>) => string
}

type SidebarProjectsColumnProps = Omit<
  SidebarProjectsSectionProps,
  'selectionMode' | 'selectedIds' | 'onToggleSelect' | 'locale'
> & {
  locale: string
  /** Rendered above the projects header (pinned threads). */
  pinnedSlot?: ReactElement | null
}

type WorkspaceGroup = [string, NormalizedThread[]]

function workspaceHasActiveThread(list: NormalizedThread[], activeThreadId: string | null): boolean {
  if (!activeThreadId) return false
  return list.some((thread) => thread.id === activeThreadId)
}

function latestWorkspaceActivity(list: NormalizedThread[]): number {
  if (list.length === 0) return 0
  return Math.max(...list.map((thread) => Date.parse(thread.updatedAt)))
}

type ProjectsToolbarProps = {
  workspaceRoot: string
  onPickWorkspace: () => void
  projectThreadCount: number
  selectMode: boolean
  selectedCount: number
  allSelected: boolean
  batchBusy: boolean
  onToggleSelectAll: () => void
  onDeleteSelected: () => void
  onExitSelectMode: () => void
  onEnterSelectMode: () => void
  onClearAll: () => void
  t: (k: string, opts?: Record<string, unknown>) => string
}

/** Fixed chrome above the sidebar scroll: matches Workspace header (collapse / + / ⋯). */
function SidebarProjectsToolbar({
  workspaceRoot,
  onPickWorkspace,
  projectThreadCount,
  selectMode,
  selectedCount,
  allSelected,
  batchBusy,
  onToggleSelectAll,
  onDeleteSelected,
  onExitSelectMode,
  onEnterSelectMode,
  onClearAll,
  t
}: ProjectsToolbarProps): ReactElement {
  const collapsed = useChatStore((s) => s.projectsCollapsed)
  const setCollapsed = useChatStore((s) => s.setProjectsCollapsed)
  const searchQuery = useChatStore((s) => s.sidebarSearchQuery)
  const searching = searchQuery.trim().length > 0
  const sectionCollapsed = searching || selectMode ? false : collapsed
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!menuOpen) return
    const onPointerDown = (event: MouseEvent): void => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setMenuOpen(false)
      }
    }
    window.addEventListener('mousedown', onPointerDown)
    return () => window.removeEventListener('mousedown', onPointerDown)
  }, [menuOpen])

  return (
    <div className="ds-sidebar-projects-toolbar ds-sidebar-projects-toolbar--fixed ds-no-drag shrink-0">
      {selectMode ? (
        <>
          <span className="ds-sidebar-section-label min-w-0 flex-1 truncate">
            {t('sidebarChatsSelectedCount', { count: selectedCount })}
          </span>
          <button
            type="button"
            onClick={onToggleSelectAll}
            disabled={projectThreadCount === 0 || batchBusy}
            className="shrink-0 rounded-md px-1.5 py-1 text-[12px] text-ds-muted transition-colors hover:bg-ds-hover hover:text-ds-ink disabled:opacity-40"
          >
            {allSelected ? t('sidebarChatsDeselectAll') : t('sidebarChatsSelectAll')}
          </button>
          <button
            type="button"
            onClick={onDeleteSelected}
            disabled={selectedCount === 0 || batchBusy}
            title={t('sidebarChatsDeleteSelected')}
            aria-label={t('sidebarChatsDeleteSelected')}
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-red-500 transition-colors hover:bg-red-50 disabled:opacity-40 dark:hover:bg-red-950/30"
          >
            {batchBusy ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={2} />
            ) : (
              <Trash2 className="h-3.5 w-3.5" strokeWidth={1.75} />
            )}
          </button>
          <button
            type="button"
            onClick={onExitSelectMode}
            disabled={batchBusy}
            title={t('sidebarChatsExitSelect')}
            aria-label={t('sidebarChatsExitSelect')}
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-ds-faint transition-colors hover:bg-ds-hover hover:text-ds-ink disabled:opacity-40"
          >
            <X className="h-3.5 w-3.5" strokeWidth={1.85} />
          </button>
        </>
      ) : (
        <>
          <button
            type="button"
            onClick={() => setCollapsed(!collapsed)}
            className="flex min-w-0 flex-1 items-center gap-1.5 text-left"
            aria-expanded={!sectionCollapsed}
          >
            {sectionCollapsed ? (
              <ChevronRight className="h-3 w-3 shrink-0 text-ds-faint" strokeWidth={2} />
            ) : (
              <ChevronDown className="h-3 w-3 shrink-0 text-ds-faint" strokeWidth={2} />
            )}
            <span className="ds-sidebar-section-label min-w-0 truncate">{t('sidebarProjects')}</span>
          </button>
          <button
            type="button"
            onClick={() => {
              setCollapsed(false)
              onPickWorkspace()
            }}
            title={workspaceRoot ? t('changeWorkspace') : t('selectWorkspace')}
            aria-label={workspaceRoot ? t('changeWorkspace') : t('selectWorkspace')}
            className="shrink-0 rounded-md p-1 text-ds-faint transition-colors duration-200 hover:bg-ds-hover/70 hover:text-ds-ink"
          >
            <Plus className="h-3.5 w-3.5" strokeWidth={1.75} />
          </button>
          <div className="relative shrink-0" ref={menuRef}>
            <button
              type="button"
              onClick={() => setMenuOpen((open) => !open)}
              title={t('sidebarProjectsMenu')}
              aria-label={t('sidebarProjectsMenu')}
              aria-expanded={menuOpen}
              className="rounded-md p-1 text-ds-faint transition-colors duration-200 hover:bg-ds-hover/70 hover:text-ds-ink"
            >
              <MoreHorizontal className="h-3.5 w-3.5" strokeWidth={1.85} />
            </button>
            {menuOpen ? (
              <div className="ds-glass absolute right-0 top-full z-50 mt-1 w-40 overflow-hidden rounded-lg py-1">
                <button
                  type="button"
                  disabled={projectThreadCount === 0}
                  onClick={() => {
                    setMenuOpen(false)
                    onEnterSelectMode()
                  }}
                  className="flex w-full items-center gap-2 px-3 py-2 text-left text-[12px] text-ds-ink hover:bg-ds-hover disabled:opacity-40"
                >
                  <CheckSquare className="h-3.5 w-3.5 shrink-0" strokeWidth={1.85} />
                  {t('sidebarChatsBatchSelect')}
                </button>
                <button
                  type="button"
                  disabled={projectThreadCount === 0 || batchBusy}
                  onClick={() => {
                    setMenuOpen(false)
                    onClearAll()
                  }}
                  className="flex w-full items-center gap-2 px-3 py-2 text-left text-[12px] text-red-600 hover:bg-red-50 disabled:opacity-40 dark:text-red-400 dark:hover:bg-red-950/20"
                >
                  <Trash2 className="h-3.5 w-3.5 shrink-0" strokeWidth={1.85} />
                  {t('sidebarChatsClearAll')}
                </button>
              </div>
            ) : null}
          </div>
        </>
      )}
    </div>
  )
}

/** Projects column: toolbar (with batch menu) + scrollable project list. */
export function SidebarProjectsColumn({
  threads,
  activeThreadId,
  runtimeReady,
  workspaceRoot,
  busy,
  watchTurnCompletion,
  unreadThreadIds,
  pinnedThreadIds,
  locale,
  pinnedSlot = null,
  onTogglePin,
  onPickWorkspace,
  onRemoveWorkspace,
  onDeleteWorkspace,
  onCreateThreadInWorkspace,
  onSelectThread,
  onOpenThreadTerminal,
  onDeleteThread,
  onCompactThread,
  t
}: SidebarProjectsColumnProps): ReactElement {
  const projectsCollapsed = useChatStore((s) => s.projectsCollapsed)
  const setProjectsCollapsed = useChatStore((s) => s.setProjectsCollapsed)
  const searchQuery = useChatStore((s) => s.sidebarSearchQuery)
  const hiddenWorkspacePaths = useChatStore((s) => s.hiddenWorkspacePaths)
  const [selectMode, setSelectMode] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set())
  const [batchBusy, setBatchBusy] = useState(false)

  const pinnedSet = useMemo(() => new Set(pinnedThreadIds), [pinnedThreadIds])

  const projectThreads = useMemo(() => {
    const query = searchQuery.trim().toLowerCase()
    return threads
      .filter((th) => {
        if (isInternalTemporaryWorkspace(th.workspace)) return false
        if (isClawWorkspacePath(th.workspace)) return false
        if (isChatsWorkspace(th.workspace)) return false
        if (pinnedSet.has(th.id)) return false
        const key = normalizeWorkspaceRoot(th.workspace)
        if (!key || isWorkspaceHidden(key, hiddenWorkspacePaths)) return false
        if (!query) return true
        const folderName = workspaceLabelFromPath(key).toLowerCase()
        return (
          folderName.includes(query) ||
          key.toLowerCase().includes(query) ||
          th.title.toLowerCase().includes(query)
        )
      })
      .sort((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt))
  }, [threads, pinnedSet, hiddenWorkspacePaths, searchQuery])

  const allSelected =
    projectThreads.length > 0 && projectThreads.every((thread) => selectedIds.has(thread.id))
  const projectsHidden = projectsCollapsed && !searchQuery.trim() && !selectMode

  useEffect(() => {
    setSelectedIds((prev) => {
      if (prev.size === 0) return prev
      const alive = new Set(projectThreads.map((thread) => thread.id))
      let changed = false
      const next = new Set<string>()
      for (const id of prev) {
        if (alive.has(id)) next.add(id)
        else changed = true
      }
      return changed ? next : prev
    })
  }, [projectThreads])

  const enterSelectMode = (): void => {
    setProjectsCollapsed(false)
    setSelectMode(true)
    setSelectedIds(new Set())
  }

  const exitSelectMode = (): void => {
    setSelectMode(false)
    setSelectedIds(new Set())
  }

  const toggleSelect = (threadId: string): void => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(threadId)) next.delete(threadId)
      else next.add(threadId)
      return next
    })
  }

  const toggleSelectAll = (): void => {
    setSelectedIds((prev) => {
      if (allSelected) return new Set()
      return new Set(projectThreads.map((thread) => thread.id))
    })
  }

  const deleteThreads = async (targets: NormalizedThread[]): Promise<void> => {
    if (targets.length === 0 || batchBusy) return
    setBatchBusy(true)
    try {
      for (const thread of targets) {
        await onDeleteThread(thread.id)
      }
      exitSelectMode()
    } finally {
      setBatchBusy(false)
    }
  }

  const handleDeleteSelected = (): void => {
    const targets = projectThreads.filter((thread) => selectedIds.has(thread.id))
    if (targets.length === 0) return
    const ok = window.confirm(
      t('sidebarProjectsDeleteSelectedConfirm', { count: targets.length })
    )
    if (!ok) return
    void deleteThreads(targets)
  }

  const handleClearAll = (): void => {
    if (projectThreads.length === 0) return
    const ok = window.confirm(
      t('sidebarProjectsClearAllConfirm', { count: projectThreads.length })
    )
    if (!ok) return
    setProjectsCollapsed(false)
    void deleteThreads(projectThreads)
  }

  return (
    <>
      {pinnedSlot}
      <SidebarProjectsToolbar
        workspaceRoot={workspaceRoot}
        onPickWorkspace={onPickWorkspace}
        projectThreadCount={projectThreads.length}
        selectMode={selectMode}
        selectedCount={selectedIds.size}
        allSelected={allSelected}
        batchBusy={batchBusy}
        onToggleSelectAll={toggleSelectAll}
        onDeleteSelected={handleDeleteSelected}
        onExitSelectMode={exitSelectMode}
        onEnterSelectMode={enterSelectMode}
        onClearAll={handleClearAll}
        t={t}
      />
      {!projectsHidden ? (
        <div className="ds-sidebar-projects-scroll ds-scroll-surface min-h-0 flex-1 overflow-y-auto overscroll-contain">
          <SidebarProjectsSection
            threads={threads}
            activeThreadId={activeThreadId}
            runtimeReady={runtimeReady}
            workspaceRoot={workspaceRoot}
            busy={busy}
            watchTurnCompletion={watchTurnCompletion}
            unreadThreadIds={unreadThreadIds}
            pinnedThreadIds={pinnedThreadIds}
            locale={locale}
            selectionMode={selectMode}
            selectedIds={selectedIds}
            onToggleSelect={toggleSelect}
            onTogglePin={onTogglePin}
            onPickWorkspace={onPickWorkspace}
            onRemoveWorkspace={onRemoveWorkspace}
            onDeleteWorkspace={onDeleteWorkspace}
            onCreateThreadInWorkspace={onCreateThreadInWorkspace}
            onSelectThread={onSelectThread}
            onOpenThreadTerminal={onOpenThreadTerminal}
            onDeleteThread={onDeleteThread}
            onCompactThread={onCompactThread}
            t={t}
          />
        </div>
      ) : null}
    </>
  )
}

function SidebarProjectsSection({
  threads,
  activeThreadId,
  runtimeReady,
  workspaceRoot,
  busy,
  watchTurnCompletion,
  unreadThreadIds,
  pinnedThreadIds,
  selectionMode = false,
  selectedIds,
  onToggleSelect,
  onTogglePin,
  onPickWorkspace,
  onRemoveWorkspace,
  onDeleteWorkspace,
  onCreateThreadInWorkspace,
  onSelectThread,
  onOpenThreadTerminal,
  onDeleteThread,
  onCompactThread,
  t
}: SidebarProjectsSectionProps): ReactElement {
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})
  const [expandedWorkspaces, setExpandedWorkspaces] = useState<Record<string, boolean>>({})
  const [deletingThreadIds, setDeletingThreadIds] = useState<Record<string, boolean>>({})
  const [folderHover, setFolderHover] = useState<{ path: string; anchor: DOMRect } | null>(null)
  const folderHoverTimerRef = useRef<number | null>(null)
  // Folder card self-dismisses after a few seconds of cursor inactivity, same as
  // the thread hover card — it is auxiliary info and should not linger.
  const folderAutoHideTimerRef = useRef<number | null>(null)
  // Branch is fetched lazily only while the folder hover card is open, keyed by
  // path. `branch === null` means "loaded, but not a git repo / no branch".
  const [folderBranch, setFolderBranch] = useState<{
    path: string
    loading: boolean
    branch: string | null
  } | null>(null)
  const searchQuery = useChatStore((s) => s.sidebarSearchQuery)
  const hiddenWorkspacePaths = useChatStore((s) => s.hiddenWorkspacePaths)
  const sidebarLabelColors = useChatStore((s) => s.sidebarLabelColors)
  const setSidebarLabelColor = useChatStore((s) => s.setSidebarLabelColor)
  const { threadIds: threadsWithActiveTasks, taskIds: activeTaskIds } = useThreadsWithActiveTasks()
  // The active conversation's task ids come straight from its loaded message
  // blocks, so it can light up even for tasks created before thread_id wiring
  // existed (no backend restart required).
  const activeThreadBlocks = useChatStore((s) => s.blocks)
  const activeThreadHasTask = useMemo(() => {
    if (!activeThreadId) return false
    return extractTasksFromBlocks(activeThreadBlocks).some((task) => activeTaskIds.has(task.id))
  }, [activeThreadId, activeThreadBlocks, activeTaskIds])
  const [projectMenu, setProjectMenu] = useState<{
    path: string
    x: number
    y: number
  } | null>(null)
  useEffect(() => {
    if (!activeThreadId) return
    const activeThread = threads.find((thread) => thread.id === activeThreadId)
    if (!activeThread) return
    const workspacePath = normalizeWorkspaceRoot(activeThread.workspace)
    if (!workspacePath) return
    if (isWorkspaceHidden(workspacePath, hiddenWorkspacePaths)) return
    setCollapsed((current) =>
      current[workspacePath] === false ? current : { ...current, [workspacePath]: false }
    )
  }, [activeThreadId, threads, hiddenWorkspacePaths])

  const pinnedSet = useMemo(() => new Set(pinnedThreadIds), [pinnedThreadIds])

  const groups = useMemo(() => {
    const map = new Map<string, NormalizedThread[]>()
    const selectedWorkspace = normalizeWorkspaceRoot(workspaceRoot)

    for (const th of threads) {
      if (isInternalTemporaryWorkspace(th.workspace)) continue
      if (isClawWorkspacePath(th.workspace)) continue
      if (isChatsWorkspace(th.workspace)) continue
      if (pinnedSet.has(th.id)) continue
      const key = normalizeWorkspaceRoot(th.workspace)
      if (!key) continue
      if (isWorkspaceHidden(key, hiddenWorkspacePaths)) continue
      const arr = map.get(key) ?? []
      arr.push(th)
      map.set(key, arr)
    }

    if (
      selectedWorkspace &&
      !isChatsWorkspace(selectedWorkspace) &&
      !isWorkspaceHidden(selectedWorkspace, hiddenWorkspacePaths) &&
      !map.has(selectedWorkspace)
    ) {
      map.set(selectedWorkspace, [])
    }

    return Array.from(map.entries()).sort(([pathA, listA], [pathB, listB]) => {
      const activityDiff = latestWorkspaceActivity(listB) - latestWorkspaceActivity(listA)
      if (activityDiff !== 0) return activityDiff
      return workspaceLabelFromPath(pathA).localeCompare(workspaceLabelFromPath(pathB))
    })
  }, [threads, workspaceRoot, pinnedSet, hiddenWorkspacePaths])

  const filteredGroups = useMemo(() => {
    const query = searchQuery.trim().toLowerCase()
    if (!query) return groups

    const result: WorkspaceGroup[] = []
    for (const [workspacePath, list] of groups) {
      const folderName = workspaceLabelFromPath(workspacePath).toLowerCase()
      const pathMatch = folderName.includes(query) || workspacePath.toLowerCase().includes(query)
      const matchingThreads = list.filter((thread) => thread.title.toLowerCase().includes(query))
      if (pathMatch) {
        result.push([workspacePath, list])
      } else if (matchingThreads.length > 0) {
        result.push([workspacePath, matchingThreads])
      }
    }
    return result
  }, [groups, searchQuery])

  const handleDeleteThread = async (thread: NormalizedThread): Promise<void> => {
    const threadId = thread.id.trim()
    if (!threadId || deletingThreadIds[threadId]) return
    const confirmMessage = t('sidebarThreadDeleteConfirm', { title: thread.title })
    if (!window.confirm(confirmMessage)) return
    setDeletingThreadIds((prev) => ({ ...prev, [threadId]: true }))
    try {
      await onDeleteThread(threadId)
    } finally {
      setDeletingThreadIds((prev) => {
        const next = { ...prev }
        delete next[threadId]
        return next
      })
    }
  }

  const handleRemoveWorkspace = async (workspacePath: string): Promise<void> => {
    const confirmMessage = t('sidebarWorkspaceRemoveConfirm', { path: workspacePath })
    if (!window.confirm(confirmMessage)) return
    await onRemoveWorkspace(workspacePath)
    setProjectMenu(null)
  }

  const handleDeleteWorkspace = async (workspacePath: string): Promise<void> => {
    const confirmMessage = t('sidebarWorkspaceDeleteFileConfirm', { path: workspacePath })
    if (!window.confirm(confirmMessage)) return
    await onDeleteWorkspace(workspacePath)
    setProjectMenu(null)
  }

  const handleOpenWorkspaceTerminal = async (workspacePath: string): Promise<void> => {
    const list = groups.find(([path]) => path === workspacePath)?.[1] ?? []
    const latest = [...list].sort(
      (a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt)
    )[0]
    if (latest) {
      await onOpenThreadTerminal(latest.id)
      return
    }
    if (typeof window.dsGui?.openTerminal === 'function') {
      await window.dsGui.openTerminal(workspacePath)
    }
  }

  const handleProjectMenuAction = (
    workspacePath: string,
    action: ProjectContextMenuAction
  ): void => {
    switch (action) {
      case 'copy-path':
        void navigator.clipboard?.writeText(workspacePath)
        break
      case 'copy-relative-path':
        void navigator.clipboard?.writeText(copyableRelativePath(workspacePath, workspacePath))
        break
      case 'new-session':
        onCreateThreadInWorkspace(workspacePath)
        break
      case 'open-with-editor':
        void openWorkspacePathInEditor({ path: workspacePath }, workspacePath)
        break
      case 'reveal-in-folder':
        void revealWorkspacePathInFolder(workspacePath)
        break
      case 'open-terminal':
        void handleOpenWorkspaceTerminal(workspacePath)
        break
      case 'remove':
        void handleRemoveWorkspace(workspacePath)
        break
      case 'delete':
        void handleDeleteWorkspace(workspacePath)
        break
    }
  }

  const renderThreadRow = (
    thread: NormalizedThread,
    options?: { variant?: ThreadRowVariant; sourceLabel?: string }
  ): ReactElement => {
    const variant = options?.variant ?? 'project'
    return (
      <ThreadRow
        key={thread.id}
        thread={thread}
        variant={variant}
        active={activeThreadId === thread.id}
        deleting={deletingThreadIds[thread.id] === true}
        showRunning={
          thread.status?.trim().toLowerCase() === 'running' ||
          (activeThreadId === thread.id && busy) ||
          watchTurnCompletion[thread.id] === true
        }
        showUnread={unreadThreadIds[thread.id] === true && activeThreadId !== thread.id}
        hasBackgroundTask={
          threadsWithActiveTasks.has(thread.id) ||
          (activeThreadId === thread.id && activeThreadHasTask)
        }
        pinned={pinnedSet.has(thread.id)}
        sourceLabel={options?.sourceLabel}
        selectionMode={selectionMode}
        selected={selectedIds?.has(thread.id) === true}
        onToggleSelect={() => onToggleSelect?.(thread.id)}
        onSelect={() => onSelectThread(thread.id)}
        onOpenTerminal={() => void onOpenThreadTerminal(thread.id)}
        onDelete={() => void handleDeleteThread(thread)}
        onCompact={() => void onCompactThread(thread.id)}
        onTogglePin={() => onTogglePin(thread.id)}
        canCompact={activeThreadId === thread.id && !busy}
      />
    )
  }

  const clearFolderHoverTimer = (): void => {
    if (folderHoverTimerRef.current != null) {
      window.clearTimeout(folderHoverTimerRef.current)
      folderHoverTimerRef.current = null
    }
  }

  const clearFolderAutoHide = (): void => {
    if (folderAutoHideTimerRef.current != null) {
      window.clearTimeout(folderAutoHideTimerRef.current)
      folderAutoHideTimerRef.current = null
    }
  }

  const armFolderAutoHide = (): void => {
    clearFolderAutoHide()
    folderAutoHideTimerRef.current = window.setTimeout(() => setFolderHover(null), 4000)
  }

  useEffect(
    () => () => {
      clearFolderHoverTimer()
      clearFolderAutoHide()
    },
    []
  )

  // Lazily resolve the git branch for whichever folder card is currently open.
  useEffect(() => {
    const path = folderHover?.path
    if (!path) {
      setFolderBranch(null)
      return
    }
    if (typeof window.dsGui?.getGitBranches !== 'function') return
    let cancelled = false
    setFolderBranch({ path, loading: true, branch: null })
    void window.dsGui
      .getGitBranches(path)
      .then((result) => {
        if (cancelled) return
        setFolderBranch({
          path,
          loading: false,
          branch: result.ok ? result.currentBranch : null
        })
      })
      .catch(() => {
        if (cancelled) return
        setFolderBranch({ path, loading: false, branch: null })
      })
    return () => {
      cancelled = true
    }
  }, [folderHover?.path])

  const renderWorkspace = ([workspacePath, list]: WorkspaceGroup): ReactElement => {
    const folderName = workspaceLabelFromPath(workspacePath)
    const searching = searchQuery.trim().length > 0
    const isCollapsed = searching || selectionMode ? false : collapsed[workspacePath] !== false
    const sortedThreads = [...list].sort((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt))
    const workspaceExpanded = expandedWorkspaces[workspacePath] === true
    const hasOverflow = !selectionMode && sortedThreads.length > 5
    const visibleThreads =
      selectionMode || workspaceExpanded ? sortedThreads : sortedThreads.slice(0, 5)
    const folderHasActive = workspaceHasActiveThread(list, activeThreadId)
    const folderIconClass = folderHasActive ? 'text-accent' : 'text-ds-muted'
    const labelColor = (sidebarLabelColors[workspaceLabelKey(workspacePath)] ??
      null) as SidebarLabelColor
    const labelSwatch = sidebarLabelSwatch(labelColor)

    return (
      <div key={workspacePath} className="mb-1">
        <div
          className="ds-sidebar-workspace group"
          onContextMenu={
            selectionMode
              ? undefined
              : (event) => {
                  event.preventDefault()
                  clearFolderHoverTimer()
                  clearFolderAutoHide()
                  setFolderHover(null)
                  setProjectMenu({ path: workspacePath, x: event.clientX, y: event.clientY })
                }
          }
          onMouseEnter={(event) => {
            const rect = event.currentTarget.getBoundingClientRect()
            clearFolderHoverTimer()
            folderHoverTimerRef.current = window.setTimeout(() => {
              setFolderHover({ path: workspacePath, anchor: rect })
              armFolderAutoHide()
            }, 500)
          }}
          onMouseMove={() => {
            if (folderHover?.path === workspacePath) armFolderAutoHide()
          }}
          onMouseLeave={() => {
            clearFolderHoverTimer()
            clearFolderAutoHide()
            setFolderHover((current) => (current?.path === workspacePath ? null : current))
          }}
        >
          <button
            type="button"
            onClick={() =>
              setCollapsed((current) => ({
                ...current,
                [workspacePath]: current[workspacePath] === false
              }))
            }
            className="flex min-h-[36px] min-w-0 flex-1 items-center gap-1.5 px-2 py-1.5 text-left"
          >
            {isCollapsed ? (
              <ChevronRight className="h-3 w-3 shrink-0 text-ds-faint" strokeWidth={2} />
            ) : (
              <ChevronDown className="h-3 w-3 shrink-0 text-ds-faint" strokeWidth={2} />
            )}
            {isCollapsed ? (
              <Folder
                className={`h-4 w-4 shrink-0 ${labelSwatch ? '' : folderIconClass}`}
                style={labelSwatch ? { color: labelSwatch } : undefined}
                strokeWidth={1.85}
                aria-hidden
              />
            ) : (
              <FolderOpen
                className={`h-4 w-4 shrink-0 ${labelSwatch ? '' : folderIconClass}`}
                style={labelSwatch ? { color: labelSwatch } : undefined}
                strokeWidth={1.85}
                aria-hidden
              />
            )}
            <span
              className="ds-sidebar-project-label min-w-0 flex-1 truncate"
              style={labelSwatch ? { color: labelSwatch } : undefined}
            >
              {folderName}
            </span>
          </button>
          {selectionMode ? null : (
            <div className="flex shrink-0 items-center gap-0.5 pr-1 opacity-40 transition-opacity duration-200 group-hover:opacity-100 group-focus-within:opacity-100 focus-within:opacity-100">
              <button
                type="button"
                onClick={(event) => {
                  event.stopPropagation()
                  onCreateThreadInWorkspace(workspacePath)
                }}
                className="rounded-md p-1 text-ds-faint transition-colors duration-200 hover:bg-ds-hover/80 hover:text-ds-ink"
                title={t('sidebarWorkspaceNewThread')}
                aria-label={t('sidebarWorkspaceNewThread')}
              >
                <Plus className="h-3.5 w-3.5" strokeWidth={1.9} />
              </button>
            </div>
          )}
        </div>

        {!isCollapsed ? (
          <div className="ds-sidebar-thread-list mt-0.5">
            {sortedThreads.length === 0 ? (
              <div className="flex items-center justify-between gap-2 px-2 py-1.5">
                <div className="text-[13px] leading-5 text-ds-faint">{t('sidebarWorkspaceEmpty')}</div>
                <button
                  type="button"
                  onClick={() => onCreateThreadInWorkspace(workspacePath)}
                  className="shrink-0 rounded-md px-2 py-1 text-[12.5px] font-medium text-ds-faint transition-colors duration-200 hover:bg-ds-hover hover:text-ds-ink"
                >
                  {t('sidebarWorkspaceNewThread')}
                </button>
              </div>
            ) : (
              visibleThreads.map((thread) => renderThreadRow(thread))
            )}
            {hasOverflow ? (
              <button
                type="button"
                onClick={() =>
                  setExpandedWorkspaces((current) => ({
                    ...current,
                    [workspacePath]: !workspaceExpanded
                  }))
                }
                className="ml-1 mt-0.5 rounded-md px-2 py-1 text-[13px] text-ds-faint transition-colors duration-200 hover:bg-ds-hover hover:text-ds-ink"
              >
                {workspaceExpanded
                  ? t('sidebarWorkspaceShowLess')
                  : t('sidebarWorkspaceShowMore', {
                      count: sortedThreads.length - 5
                    })}
              </button>
            ) : null}
          </div>
        ) : null}
      </div>
    )
  }

  const noProjects = groups.length === 0
  const noVisible = filteredGroups.length === 0

  return (
    <div className="ds-no-drag shrink-0 px-1 pt-1">
      <div className="ds-sidebar-projects-panel">
        <div className="px-1.5 pb-2 pt-1">
          {filteredGroups.length > 0 ? (
            <div className="mb-1">{filteredGroups.map(renderWorkspace)}</div>
          ) : null}

          {noVisible ? (
            noProjects ? (
              <SidebarEmpty
                runtimeReady={runtimeReady}
                hasWorkspace={!!workspaceRoot}
                onPickWorkspace={onPickWorkspace}
                t={t}
              />
            ) : (
              <div className="px-1 py-3 text-[13px] text-ds-faint">{t('sidebarSearchNoResults')}</div>
            )
          ) : null}
        </div>
      </div>
      {folderHover && !projectMenu ? (
        <HoverInfoCard
          anchor={folderHover.anchor}
          titleIcon={Folder}
          title={workspaceLabelFromPath(folderHover.path)}
          rows={[
            {
              icon: MessageSquare,
              text: t('sidebarProjectThreadCount', {
                count: groups.find(([path]) => path === folderHover.path)?.[1].length ?? 0
              })
            },
            ...(folderBranch?.path === folderHover.path &&
            (folderBranch.loading || folderBranch.branch)
              ? [
                  {
                    icon: GitBranch,
                    text: folderBranch.loading
                      ? t('sidebarProjectBranchLoading')
                      : (folderBranch.branch as string)
                  }
                ]
              : []),
            { icon: FolderClosed, text: folderHover.path, divider: true }
          ]}
        />
      ) : null}
      {projectMenu ? (
        <ProjectContextMenu
          x={projectMenu.x}
          y={projectMenu.y}
          labelColor={
            (sidebarLabelColors[workspaceLabelKey(projectMenu.path)] ?? null) as SidebarLabelColor
          }
          onLabelColorChange={(color) =>
            setSidebarLabelColor(workspaceLabelKey(projectMenu.path), color)
          }
          onAction={(action) => handleProjectMenuAction(projectMenu.path, action)}
          onClose={() => setProjectMenu(null)}
          t={t}
        />
      ) : null}
    </div>
  )
}

export type ThreadRowVariant = 'project' | 'pinned' | 'chats'

type ThreadRowProps = {
  thread: NormalizedThread
  variant: ThreadRowVariant
  active: boolean
  deleting: boolean
  showRunning: boolean
  showUnread: boolean
  hasBackgroundTask: boolean
  pinned: boolean
  sourceLabel?: string
  canCompact: boolean
  /** Workspace batch-manage mode: row toggles selection instead of opening. */
  selectionMode?: boolean
  selected?: boolean
  onToggleSelect?: () => void
  onSelect: () => void
  onOpenTerminal: () => void
  onDelete: () => void
  onCompact: () => void
  onTogglePin: () => void
}

export function ThreadRow({
  thread,
  variant,
  active,
  deleting,
  showRunning,
  showUnread,
  hasBackgroundTask,
  pinned,
  sourceLabel,
  canCompact,
  selectionMode = false,
  selected = false,
  onToggleSelect,
  onSelect,
  onOpenTerminal,
  onDelete,
  onCompact,
  onTogglePin
}: ThreadRowProps): ReactElement {
  const { t } = useTranslation('common')
  const renameThread = useChatStore((s) => s.renameThread)
  const markThreadUnread = useChatStore((s) => s.markThreadUnread)
  const activeThreadId = useChatStore((s) => s.activeThreadId)
  const sidebarLabelColors = useChatStore((s) => s.sidebarLabelColors)
  const setSidebarLabelColor = useChatStore((s) => s.setSidebarLabelColor)
  const [menuPos, setMenuPos] = useState<{ x: number; y: number } | null>(null)
  // Inline rename: Electron's renderer has no window.prompt, so the row turns
  // into an editable input (mirrors the title editor in SessionHeader).
  const [renaming, setRenaming] = useState(false)
  const [draftTitle, setDraftTitle] = useState(thread.title)
  const [hoverAnchor, setHoverAnchor] = useState<DOMRect | null>(null)
  const hoverTimerRef = useRef<number | null>(null)
  // The hover card is auxiliary info: once shown it self-dismisses after a few
  // seconds of cursor inactivity so it does not linger over the sidebar/content.
  const autoHideTimerRef = useRef<number | null>(null)
  // A detached background task counts as activity even when the chat turn is
  // idle; only fall back to the blue unread dot when nothing is in flight.
  const showTaskDot = hasBackgroundTask && !showRunning
  const showUnreadDot = showUnread && !showRunning && !showTaskDot

  // All rows surface thread completion: green check for completed/idle.
  const status = thread.status?.trim().toLowerCase()
  const showCompleted = !showRunning && (status === 'completed' || status === 'idle')

  const threadPath = normalizeWorkspaceRoot(thread.workspace)
  const hasPath = threadPath.length > 0 && !isInternalTemporaryWorkspace(thread.workspace)
  const projectLabel = isChatsWorkspace(thread.workspace)
    ? t('sidebarChatBadge')
    : workspaceLabelFromPath(threadPath)

  const clearHoverTimer = (): void => {
    if (hoverTimerRef.current != null) {
      window.clearTimeout(hoverTimerRef.current)
      hoverTimerRef.current = null
    }
  }

  const clearAutoHideTimer = (): void => {
    if (autoHideTimerRef.current != null) {
      window.clearTimeout(autoHideTimerRef.current)
      autoHideTimerRef.current = null
    }
  }

  // Restart the 4s inactivity countdown; called when the card first appears and
  // on every cursor move over the row so an actively-read card stays open.
  const armAutoHide = (): void => {
    clearAutoHideTimer()
    autoHideTimerRef.current = window.setTimeout(() => setHoverAnchor(null), 4000)
  }

  useEffect(
    () => () => {
      clearHoverTimer()
      clearAutoHideTimer()
    },
    []
  )

  const handleRowMouseEnter = (event: ReactMouseEvent<HTMLDivElement>): void => {
    const rect = event.currentTarget.getBoundingClientRect()
    clearHoverTimer()
    hoverTimerRef.current = window.setTimeout(() => {
      setHoverAnchor(rect)
      armAutoHide()
    }, 500)
  }

  const handleRowMouseMove = (): void => {
    // Only matters once the card is visible; reset its inactivity countdown.
    if (hoverAnchor) armAutoHide()
  }

  const handleRowMouseLeave = (): void => {
    clearHoverTimer()
    clearAutoHideTimer()
    setHoverAnchor(null)
  }

  const handleContextMenu = (event: ReactMouseEvent<HTMLDivElement>): void => {
    event.preventDefault()
    clearHoverTimer()
    clearAutoHideTimer()
    setHoverAnchor(null)
    setMenuPos({ x: event.clientX, y: event.clientY })
  }

  const commitRename = (): void => {
    const next = draftTitle.trim()
    if (next && next !== thread.title) void renameThread(thread.id, next)
    setRenaming(false)
  }

  const cancelRename = (): void => {
    setDraftTitle(thread.title)
    setRenaming(false)
  }

  const labelColor = (sidebarLabelColors[threadLabelKey(thread.id)] ?? null) as SidebarLabelColor
  const labelSwatch = sidebarLabelSwatch(labelColor)

  const handleMenuAction = (action: ThreadContextMenuAction): void => {
    switch (action) {
      case 'rename':
        // Electron's renderer has no window.prompt; edit the title inline.
        setDraftTitle(thread.title)
        setRenaming(true)
        break
      case 'toggle-pin':
        onTogglePin()
        break
      case 'mark-unread':
        markThreadUnread(thread.id)
        break
      case 'copy-path':
        if (threadPath) void navigator.clipboard?.writeText(threadPath)
        break
      case 'copy-relative-path':
        if (threadPath) {
          void navigator.clipboard?.writeText(copyableRelativePath(threadPath, threadPath))
        }
        break
      case 'open-with-editor':
        if (threadPath) void openWorkspacePathInEditor({ path: threadPath }, threadPath)
        break
      case 'reveal-in-folder':
        if (threadPath) void revealWorkspacePathInFolder(threadPath)
        break
      case 'open-terminal':
        // Open the built-in right-side terminal panel (cd'd to this thread's
        // workspace), not the OS terminal.
        onOpenTerminal()
        break
      case 'copy-thread-id':
        void navigator.clipboard?.writeText(thread.id)
        break
      case 'delete':
        onDelete()
        break
    }
  }

  return (
    <div
      onContextMenu={selectionMode ? undefined : handleContextMenu}
      onMouseEnter={selectionMode ? undefined : handleRowMouseEnter}
      onMouseMove={selectionMode ? undefined : handleRowMouseMove}
      onMouseLeave={selectionMode ? undefined : handleRowMouseLeave}
      className={`ds-sidebar-thread-row group relative flex min-w-0 items-center overflow-hidden ${
        renaming
          ? ''
          : selectionMode && selected
            ? 'ds-sidebar-thread-row--active'
            : !selectionMode && active
              ? 'ds-sidebar-thread-row--active'
              : ''
      }`}
    >
      <button
        type="button"
        onClick={
          renaming
            ? undefined
            : selectionMode
              ? onToggleSelect
              : onSelect
        }
        className="ds-density-list-row relative flex min-w-0 flex-1 items-center gap-2.5 pl-2.5 pr-2 text-left"
        disabled={deleting}
        aria-pressed={selectionMode ? selected : undefined}
        aria-label={
          selectionMode
            ? thread.title
            : showRunning
              ? `${thread.title} — ${t('sidebarThreadRunning')}`
              : showTaskDot
                ? `${thread.title} — ${t('sidebarThreadTaskRunning')}`
                : showUnreadDot
                  ? `${thread.title} — ${t('sidebarThreadUnread')}`
                  : thread.title
        }
      >
        <span className="flex h-4 w-4 shrink-0 items-center justify-center text-ds-muted/70">
          {selectionMode ? (
            selected ? (
              <CheckSquare className="h-3.5 w-3.5 text-accent" strokeWidth={2} aria-hidden />
            ) : (
              <Square className="h-3.5 w-3.5" strokeWidth={1.85} aria-hidden />
            )
          ) : showRunning ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin text-accent" strokeWidth={2.1} />
          ) : showTaskDot ? (
            <span
              className="block h-1.5 w-1.5 animate-pulse rounded-full bg-amber-500 dark:bg-amber-400"
              title={t('sidebarThreadTaskRunning')}
            />
          ) : showUnreadDot ? (
            <span
              className="block h-1.5 w-1.5 rounded-full bg-accent"
              title={t('sidebarThreadUnread')}
            />
          ) : (
            <MessageSquare className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
          )}
        </span>
        {renaming ? (
          <input
            value={draftTitle}
            onChange={(event) => setDraftTitle(event.target.value)}
            onClick={(event) => event.stopPropagation()}
            onBlur={commitRename}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault()
                commitRename()
              } else if (event.key === 'Escape') {
                event.preventDefault()
                cancelRename()
              }
            }}
            autoFocus
            onFocus={(event) => event.currentTarget.select()}
            className="ds-sidebar-thread min-w-0 flex-1 truncate border-0 bg-transparent p-0 text-ds-ink caret-accent outline-none"
          />
        ) : (
          <span
            className={[
              'ds-sidebar-thread min-w-0 flex-1 truncate',
              showUnreadDot ? 'ds-sidebar-thread--emphasis' : ''
            ].join(' ')}
            style={labelSwatch ? { color: labelSwatch } : undefined}
            title={thread.title}
          >
            {(() => {
              const focus = parseUserFocusPrefix(thread.title)
              return focus ? focus.body || focus.name : thread.title
            })()}
          </span>
        )}
        {selectionMode ? null : (
          <span
            className="ds-sidebar-thread-meta group-hover:hidden group-focus-within:hidden"
            title={
              showCompleted
                ? t('sidebarThreadCompleted')
                : (sourceLabel ?? formatRelativeTimeLargestUnit(thread.updatedAt))
            }
          >
            {showCompleted ? (
              <Check
                className="h-3.5 w-3.5 text-emerald-500 dark:text-emerald-400"
                strokeWidth={2.25}
                aria-hidden
              />
            ) : (
              <span className="min-w-0 truncate">
                {sourceLabel ?? formatRelativeTimeLargestUnit(thread.updatedAt)}
              </span>
            )}
          </span>
        )}
      </button>
      <div
        className={`hidden shrink-0 items-center gap-0.5 pr-1 group-hover:flex group-focus-within:flex focus-within:flex ${
          selectionMode ? '!hidden' : ''
        }`}
      >
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation()
            onTogglePin()
          }}
          disabled={deleting}
          className={`flex h-6 w-6 items-center justify-center rounded-md transition-colors duration-200 hover:bg-ds-hover hover:text-ds-ink ${
            pinned ? 'text-accent' : 'text-ds-faint'
          }`}
          title={pinned ? t('sidebarUnpinThread') : t('sidebarPinThread')}
          aria-label={pinned ? t('sidebarUnpinThread') : t('sidebarPinThread')}
        >
          {pinned ? (
            <PinOff className="h-3.5 w-3.5" strokeWidth={1.9} />
          ) : (
            <Pin className="h-3.5 w-3.5" strokeWidth={1.9} />
          )}
        </button>
        {canCompact ? (
          <button
            type="button"
            onClick={(event) => {
              event.stopPropagation()
              onCompact()
            }}
            disabled={deleting}
            className="flex h-6 w-6 items-center justify-center rounded-md text-ds-faint transition-colors duration-200 hover:bg-ds-hover hover:text-ds-ink"
            title={t('sidebarThreadCompact')}
            aria-label={t('sidebarThreadCompact')}
          >
            <Archive className="h-3.5 w-3.5" strokeWidth={1.9} />
          </button>
        ) : null}
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation()
            onDelete()
          }}
          disabled={deleting}
          className="flex h-6 w-6 items-center justify-center rounded-md text-ds-faint transition-colors duration-200 hover:bg-ds-hover hover:text-red-600 disabled:cursor-not-allowed disabled:opacity-100"
          title={t('sidebarThreadDelete')}
          aria-label={t('sidebarThreadDelete')}
        >
          {deleting ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={2} />
          ) : (
            <Trash2 className="h-3.5 w-3.5" strokeWidth={1.9} />
          )}
        </button>
      </div>
      {!selectionMode && hoverAnchor && !menuPos ? (
        <HoverInfoCard
          anchor={hoverAnchor}
          titleIcon={MessageSquare}
          title={thread.title}
          rows={[
            { icon: Clock, text: formatRelativeTimeLargestUnit(thread.updatedAt) },
            ...(projectLabel ? [{ icon: FolderClosed, text: projectLabel, divider: true }] : [])
          ]}
        />
      ) : null}
      {!selectionMode && menuPos ? (
        <ThreadContextMenu
          x={menuPos.x}
          y={menuPos.y}
          openUp={variant === 'chats'}
          pinned={pinned}
          canMarkUnread={activeThreadId !== thread.id}
          hasPath={hasPath}
          labelColor={labelColor}
          onLabelColorChange={(color) =>
            setSidebarLabelColor(threadLabelKey(thread.id), color)
          }
          onAction={handleMenuAction}
          onClose={() => setMenuPos(null)}
          t={t}
        />
      ) : null}
    </div>
  )
}

type SidebarEmptyProps = {
  runtimeReady: boolean
  hasWorkspace: boolean
  onPickWorkspace: () => void
  t: (k: string, opts?: Record<string, unknown>) => string
}

function SidebarEmpty({
  runtimeReady,
  hasWorkspace,
  onPickWorkspace,
  t
}: SidebarEmptyProps): ReactElement {
  if (!hasWorkspace && runtimeReady) {
    return (
      <button
        type="button"
        onClick={onPickWorkspace}
        className="ds-sidebar-link ds-sidebar-link--plain mx-1 mt-1 w-[calc(100%-0.5rem)]"
      >
        <span className="ds-sidebar-link__icon text-accent">
          <LayoutGrid className="h-4 w-4 shrink-0" strokeWidth={1.75} />
        </span>
        <span className="min-w-0 flex-1 truncate">{t('selectWorkspace')}</span>
      </button>
    )
  }

  return (
    <div className="ds-sidebar-empty-copy mx-2 mt-2 rounded-lg px-2 py-2">
      <p className="text-[16px] font-semibold text-ds-ink">{t('sidebarEmptyTitle')}</p>
      <p className="mt-1.5 text-[14px] leading-5 text-ds-muted">
        {runtimeReady ? t('sidebarEmptySub') : t('sidebarEmptySubOffline')}
      </p>
    </div>
  )
}
