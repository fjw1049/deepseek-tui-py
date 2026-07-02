import type { MouseEvent as ReactMouseEvent, ReactElement } from 'react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Check,
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
  Pin,
  PinOff,
  Plus,
  Trash2,
  Archive,
  Download,
  Search
} from 'lucide-react'
import type { NormalizedThread } from '../../agent/types'
import { useThreadsWithActiveTasks } from '../../hooks/use-thread-tasks'
import { extractTasksFromBlocks } from '../../lib/extract-tasks-from-blocks'
import { useChatStore } from '../../store/chat-store'
import { formatRelativeTimeLargestUnit } from '../../lib/format-relative-time'
import { workspaceLabelFromPath } from '../../lib/workspace-label'
import {
  isChatsWorkspace,
  isClawWorkspacePath,
  isInternalTemporaryWorkspace,
  normalizeWorkspaceRoot
} from '../../lib/workspace-path'
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
  onTogglePin: (threadId: string) => void
  onPickWorkspace: () => void
  onRemoveWorkspace: (workspacePath: string) => Promise<void>
  onCreateThreadInWorkspace: (workspacePath: string) => void
  onImportSession: () => void
  onSelectThread: (threadId: string) => void
  onOpenThreadTerminal: (threadId: string) => Promise<void>
  onDeleteThread: (threadId: string) => Promise<void>
  onCompactThread: (threadId: string) => Promise<void>
  t: (k: string, opts?: Record<string, unknown>) => string
}

type WorkspaceGroup = [string, NormalizedThread[]]

const PROJECT_ICON_TINTS = [
  'text-sky-500/85 dark:text-sky-400/85',
  'text-violet-500/85 dark:text-violet-400/85',
  'text-emerald-500/85 dark:text-emerald-400/85',
  'text-amber-500/90 dark:text-amber-400/85',
  'text-rose-500/85 dark:text-rose-400/85',
  'text-cyan-500/85 dark:text-cyan-400/85'
] as const

function workspaceIconTint(path: string): string {
  let hash = 0
  for (let i = 0; i < path.length; i += 1) {
    hash = path.charCodeAt(i) + ((hash << 5) - hash)
  }
  return PROJECT_ICON_TINTS[Math.abs(hash) % PROJECT_ICON_TINTS.length]
}

function latestWorkspaceActivity(list: NormalizedThread[]): number {
  if (list.length === 0) return 0
  return Math.max(...list.map((thread) => Date.parse(thread.updatedAt)))
}

export function SidebarProjectsSection({
  threads,
  activeThreadId,
  runtimeReady,
  workspaceRoot,
  busy,
  watchTurnCompletion,
  unreadThreadIds,
  pinnedThreadIds,
  onTogglePin,
  onPickWorkspace,
  onRemoveWorkspace,
  onCreateThreadInWorkspace,
  onImportSession,
  onSelectThread,
  onOpenThreadTerminal,
  onDeleteThread,
  onCompactThread,
  t
}: SidebarProjectsSectionProps): ReactElement {
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})
  const [expandedWorkspaces, setExpandedWorkspaces] = useState<Record<string, boolean>>({})
  const [deletingThreadIds, setDeletingThreadIds] = useState<Record<string, boolean>>({})
  const [searchExpanded, setSearchExpanded] = useState(false)
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
  const setSearchQuery = useChatStore((s) => s.setSidebarSearchQuery)
  const searchInputRef = useRef<HTMLInputElement>(null)
  const searchOpen = searchExpanded || searchQuery.trim().length > 0
  const { threadIds: threadsWithActiveTasks, taskIds: activeTaskIds } = useThreadsWithActiveTasks()
  // The active conversation's task ids come straight from its loaded message
  // blocks, so it can light up even for tasks created before thread_id wiring
  // existed (no backend restart required).
  const activeThreadBlocks = useChatStore((s) => s.blocks)
  const activeThreadHasTask = useMemo(() => {
    if (!activeThreadId) return false
    return extractTasksFromBlocks(activeThreadBlocks).some((task) => activeTaskIds.has(task.id))
  }, [activeThreadId, activeThreadBlocks, activeTaskIds])

  useEffect(() => {
    if (!searchOpen) return
    searchInputRef.current?.focus()
  }, [searchOpen])

  useEffect(() => {
    if (!activeThreadId) return
    const activeThread = threads.find((thread) => thread.id === activeThreadId)
    if (!activeThread) return
    const workspacePath = normalizeWorkspaceRoot(activeThread.workspace)
    if (!workspacePath) return
    setCollapsed((current) =>
      current[workspacePath] === false ? current : { ...current, [workspacePath]: false }
    )
  }, [activeThreadId, threads])

  const pinnedSet = useMemo(() => new Set(pinnedThreadIds), [pinnedThreadIds])

  // Pinned threads, ordered by pin time (the pinnedThreadIds array order).
  // Dropped ids whose thread no longer exists are skipped.
  const pinnedThreads = useMemo(() => {
    const byId = new Map(threads.map((thread) => [thread.id, thread]))
    return pinnedThreadIds
      .map((id) => byId.get(id))
      .filter((thread): thread is NormalizedThread => thread !== undefined)
  }, [threads, pinnedThreadIds])

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
      const arr = map.get(key) ?? []
      arr.push(th)
      map.set(key, arr)
    }

    if (selectedWorkspace && !isChatsWorkspace(selectedWorkspace) && !map.has(selectedWorkspace)) {
      map.set(selectedWorkspace, [])
    }

    return Array.from(map.entries()).sort(([pathA, listA], [pathB, listB]) => {
      const activityDiff = latestWorkspaceActivity(listB) - latestWorkspaceActivity(listA)
      if (activityDiff !== 0) return activityDiff
      return workspaceLabelFromPath(pathA).localeCompare(workspaceLabelFromPath(pathB))
    })
  }, [threads, workspaceRoot, pinnedSet])

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

  const filteredPinnedThreads = useMemo(() => {
    const query = searchQuery.trim().toLowerCase()
    if (!query) return pinnedThreads
    return pinnedThreads.filter((thread) => thread.title.toLowerCase().includes(query))
  }, [pinnedThreads, searchQuery])

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
        onSelect={() => onSelectThread(thread.id)}
        onOpenTerminal={() => void onOpenThreadTerminal(thread.id)}
        onDelete={() => void handleDeleteThread(thread)}
        onCompact={() => void onCompactThread(thread.id)}
        onTogglePin={() => onTogglePin(thread.id)}
        canCompact={activeThreadId === thread.id && !busy}
      />
    )
  }

  const pinnedSourceLabel = (thread: NormalizedThread): string => {
    if (isChatsWorkspace(thread.workspace)) return t('sidebarChatBadge')
    return workspaceLabelFromPath(normalizeWorkspaceRoot(thread.workspace))
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
    const isCollapsed = searching ? false : collapsed[workspacePath] !== false
    const sortedThreads = [...list].sort((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt))
    const workspaceExpanded = expandedWorkspaces[workspacePath] === true
    const hasOverflow = sortedThreads.length > 5
    const visibleThreads = workspaceExpanded ? sortedThreads : sortedThreads.slice(0, 5)

    return (
      <div key={workspacePath} className="mb-1">
        <div
          className="ds-sidebar-workspace group"
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
                className={`h-4 w-4 shrink-0 ${workspaceIconTint(workspacePath)}`}
                strokeWidth={1.85}
                aria-hidden
              />
            ) : (
              <FolderOpen
                className={`h-4 w-4 shrink-0 ${workspaceIconTint(workspacePath)}`}
                strokeWidth={1.85}
                aria-hidden
              />
            )}
            <span className="ds-sidebar-project-label min-w-0 flex-1 truncate">{folderName}</span>
            <span className="ds-sidebar-project-count">{list.length}</span>
          </button>
          <div className="flex shrink-0 items-center gap-0.5 pr-1 opacity-0 transition-opacity duration-200 group-hover:opacity-100 focus-within:opacity-100">
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
            <button
              type="button"
              onClick={(event) => {
                event.stopPropagation()
                void handleRemoveWorkspace(workspacePath)
              }}
              className="rounded-md p-1 text-ds-faint transition-colors duration-200 hover:bg-ds-hover/80 hover:text-red-500"
              title={t('sidebarWorkspaceRemove')}
              aria-label={t('sidebarWorkspaceRemove')}
            >
              <Trash2 className="h-3.5 w-3.5" strokeWidth={1.9} />
            </button>
          </div>
        </div>

        {!isCollapsed ? (
          <div className="ds-sidebar-thread-list mt-0.5 space-y-0.5">
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

  const noProjectsAndPinned = groups.length === 0 && pinnedThreads.length === 0
  const noVisible = filteredPinnedThreads.length === 0 && filteredGroups.length === 0

  return (
    <div className="ds-no-drag flex min-h-0 flex-1 flex-col px-1">
      {filteredPinnedThreads.length > 0 ? (
        <div className="mb-1">
          <div className="ds-sidebar-projects-toolbar">
            <span className="ds-sidebar-section-label shrink-0">{t('sidebarPinned')}</span>
          </div>
          <div className="ds-sidebar-thread-list space-y-0.5 px-1.5">
            {filteredPinnedThreads.map((thread) =>
              renderThreadRow(thread, { variant: 'pinned', sourceLabel: pinnedSourceLabel(thread) })
            )}
          </div>
        </div>
      ) : null}

      <div className="ds-sidebar-projects-panel flex min-h-0 flex-1 flex-col">
        <div className="ds-sidebar-projects-toolbar">
          <span className="ds-sidebar-section-label shrink-0">{t('sidebarProjects')}</span>
          {searchOpen ? (
            <label className="relative min-w-0 flex-1">
              <Search
                className="pointer-events-none absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-ds-faint"
                strokeWidth={2}
                aria-hidden
              />
              <input
                ref={searchInputRef}
                type="search"
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                onBlur={() => {
                  if (!searchQuery.trim()) setSearchExpanded(false)
                }}
                onKeyDown={(event) => {
                  if (event.key !== 'Escape') return
                  event.preventDefault()
                  if (searchQuery.trim()) {
                    setSearchQuery('')
                    return
                  }
                  setSearchExpanded(false)
                  searchInputRef.current?.blur()
                }}
                placeholder={t('sidebarSearchProjects')}
                aria-label={t('sidebarSearchProjects')}
                className="ds-sidebar-search ds-sidebar-search--inline w-full pl-7"
              />
            </label>
          ) : (
            <div className="min-w-0 flex-1" aria-hidden />
          )}
          <div className="flex shrink-0 items-center gap-0.5">
            {!searchOpen ? (
              <button
                type="button"
                onClick={() => setSearchExpanded(true)}
                title={t('sidebarSearchProjects')}
                aria-label={t('sidebarSearchProjects')}
                className="rounded-md p-1 text-ds-faint transition-colors duration-200 hover:bg-ds-hover/70 hover:text-ds-ink"
              >
                <Search className="h-3.5 w-3.5" strokeWidth={1.75} />
              </button>
            ) : null}
            <button
              type="button"
              onClick={onImportSession}
              title={t('importSession')}
              className="rounded-md p-1 text-ds-faint transition-colors duration-200 hover:bg-ds-hover/70 hover:text-ds-ink"
            >
              <Download className="h-3.5 w-3.5" strokeWidth={1.75} />
            </button>
            <button
              type="button"
              onClick={onPickWorkspace}
              title={workspaceRoot ? t('changeWorkspace') : t('selectWorkspace')}
              className="rounded-md p-1 text-ds-faint transition-colors duration-200 hover:bg-ds-hover/70 hover:text-ds-ink"
            >
              <Plus className="h-3.5 w-3.5" strokeWidth={1.75} />
            </button>
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-1.5 pb-2 pt-1">
          {filteredGroups.length > 0 ? (
            <div className="mb-1">{filteredGroups.map(renderWorkspace)}</div>
          ) : null}

          {noVisible ? (
            noProjectsAndPinned ? (
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
      {folderHover ? (
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
      onContextMenu={handleContextMenu}
      onMouseEnter={handleRowMouseEnter}
      onMouseMove={handleRowMouseMove}
      onMouseLeave={handleRowMouseLeave}
      className={`group relative flex min-w-0 items-center overflow-hidden rounded-[10px] transition-colors duration-200 ${
        renaming
          ? ''
          : active
            ? 'bg-black/[0.045] text-ds-ink dark:bg-white/[0.055]'
            : 'hover:bg-ds-hover/40 dark:hover:bg-white/[0.03]'
      }`}
    >
      <button
        type="button"
        onClick={renaming ? undefined : onSelect}
        className="ds-density-list-row relative flex min-w-0 flex-1 items-center gap-1.5 pl-2.5 pr-2.5 text-left"
        disabled={deleting}
        aria-label={
          showRunning
            ? `${thread.title} — ${t('sidebarThreadRunning')}`
            : showTaskDot
              ? `${thread.title} — ${t('sidebarThreadTaskRunning')}`
              : showUnreadDot
                ? `${thread.title} — ${t('sidebarThreadUnread')}`
                : thread.title
        }
      >
        <span className="flex h-3.5 w-3.5 shrink-0 items-center justify-center text-ds-faint">
          {showRunning ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin text-accent" strokeWidth={2} />
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
            <MessageSquare className="h-3.5 w-3.5" strokeWidth={1.75} aria-hidden />
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
          >
            {thread.title}
          </span>
        )}
        {showCompleted ? (
          <span
            className="flex h-3.5 w-3.5 shrink-0 items-center justify-center text-emerald-500 group-hover:hidden dark:text-emerald-400"
            title={t('sidebarThreadCompleted')}
            aria-hidden
          >
            <Check className="h-3.5 w-3.5" strokeWidth={2.25} />
          </span>
        ) : (
          <span className="ds-sidebar-thread-meta hidden shrink-0 truncate" title={sourceLabel}>
            {sourceLabel ?? formatRelativeTimeLargestUnit(thread.updatedAt)}
          </span>
        )}
      </button>
      <div className="hidden shrink-0 items-center gap-0.5 pr-1 group-hover:flex group-focus-within:flex focus-within:flex">
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
      {hoverAnchor && !menuPos ? (
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
      {menuPos ? (
        <ThreadContextMenu
          x={menuPos.x}
          y={menuPos.y}
          openUp={variant === 'chats'}
          pinned={pinned}
          canMarkUnread={activeThreadId !== thread.id}
          hasPath={hasPath}
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
