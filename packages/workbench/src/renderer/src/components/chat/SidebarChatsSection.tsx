import type { ReactElement } from 'react'
import { useEffect, useMemo, useRef, useState } from 'react'
import {
  CheckSquare,
  ChevronDown,
  ChevronRight,
  Loader2,
  MoreHorizontal,
  Plus,
  Trash2,
  X
} from 'lucide-react'
import type { NormalizedThread } from '../../agent/types'
import { useThreadsWithActiveTasks } from '../../hooks/use-thread-tasks'
import { extractTasksFromBlocks } from '../../lib/extract-tasks-from-blocks'
import { useChatStore } from '../../store/chat-store'
import { isChatsWorkspace, isClawWorkspacePath } from '../../lib/workspace-path'
import { ThreadRow } from './SidebarProjectsSection'

const CHATS_VISIBLE_LIMIT = 8

type SidebarChatsSectionProps = {
  onNewChat: () => void
  onSelectThread: (threadId: string) => void
  onOpenThreadTerminal: (threadId: string) => Promise<void>
  onDeleteThread: (threadId: string) => Promise<void>
  onCompactThread: (threadId: string) => Promise<void>
  onTogglePin: (threadId: string) => void
  t: (k: string, opts?: Record<string, unknown>) => string
}

export function SidebarChatsSection({
  onNewChat,
  onSelectThread,
  onOpenThreadTerminal,
  onDeleteThread,
  onCompactThread,
  onTogglePin,
  t
}: SidebarChatsSectionProps): ReactElement {
  const threads = useChatStore((s) => s.threads)
  const activeThreadId = useChatStore((s) => s.activeThreadId)
  const pinnedThreadIds = useChatStore((s) => s.pinnedThreadIds)
  const searchQuery = useChatStore((s) => s.sidebarSearchQuery)
  const busy = useChatStore((s) => s.busy)
  const watchTurnCompletion = useChatStore((s) => s.watchTurnCompletion)
  const unreadThreadIds = useChatStore((s) => s.unreadThreadIds)
  const activeThreadBlocks = useChatStore((s) => s.blocks)
  const { threadIds: threadsWithActiveTasks, taskIds: activeTaskIds } = useThreadsWithActiveTasks()

  const collapsed = useChatStore((s) => s.chatsCollapsed)
  const setCollapsed = useChatStore((s) => s.setChatsCollapsed)
  const [expanded, setExpanded] = useState(false)
  const [deletingThreadIds, setDeletingThreadIds] = useState<Record<string, boolean>>({})
  const [menuOpen, setMenuOpen] = useState(false)
  const [selectMode, setSelectMode] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set())
  const [batchBusy, setBatchBusy] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  const pinnedSet = useMemo(() => new Set(pinnedThreadIds), [pinnedThreadIds])

  const activeThreadHasTask = useMemo(() => {
    if (!activeThreadId) return false
    return extractTasksFromBlocks(activeThreadBlocks).some((task) => activeTaskIds.has(task.id))
  }, [activeThreadId, activeThreadBlocks, activeTaskIds])

  // Chats bucket: temp/default-workspace threads not belonging to a user-added
  // project and not pinned. Claw threads stay excluded as elsewhere.
  const chatsThreads = useMemo(() => {
    return threads
      .filter(
        (th) =>
          !isClawWorkspacePath(th.workspace) &&
          isChatsWorkspace(th.workspace) &&
          !pinnedSet.has(th.id)
      )
      .sort((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt))
  }, [threads, pinnedSet])

  const filteredChats = useMemo(() => {
    const query = searchQuery.trim().toLowerCase()
    if (!query) return chatsThreads
    return chatsThreads.filter((thread) => thread.title.toLowerCase().includes(query))
  }, [chatsThreads, searchQuery])

  const hasOverflow = !selectMode && filteredChats.length > CHATS_VISIBLE_LIMIT
  const visibleChats =
    selectMode || expanded ? filteredChats : filteredChats.slice(0, CHATS_VISIBLE_LIMIT)

  const allVisibleSelected =
    visibleChats.length > 0 && visibleChats.every((thread) => selectedIds.has(thread.id))

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

  // Drop selections for threads that disappeared.
  useEffect(() => {
    setSelectedIds((prev) => {
      if (prev.size === 0) return prev
      const alive = new Set(filteredChats.map((thread) => thread.id))
      let changed = false
      const next = new Set<string>()
      for (const id of prev) {
        if (alive.has(id)) next.add(id)
        else changed = true
      }
      return changed ? next : prev
    })
  }, [filteredChats])

  const enterSelectMode = (): void => {
    setMenuOpen(false)
    setCollapsed(false)
    setExpanded(true)
    setSelectMode(true)
    setSelectedIds(new Set())
  }

  const exitSelectMode = (): void => {
    setSelectMode(false)
    setSelectedIds(new Set())
    setMenuOpen(false)
  }

  const toggleSelect = (threadId: string): void => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(threadId)) next.delete(threadId)
      else next.add(threadId)
      return next
    })
  }

  const toggleSelectAllVisible = (): void => {
    setSelectedIds((prev) => {
      if (allVisibleSelected) return new Set()
      return new Set(visibleChats.map((thread) => thread.id))
    })
  }

  const deleteThreads = async (targets: NormalizedThread[]): Promise<void> => {
    if (targets.length === 0 || batchBusy) return
    setBatchBusy(true)
    const ids = targets.map((thread) => thread.id)
    setDeletingThreadIds((prev) => {
      const next = { ...prev }
      for (const id of ids) next[id] = true
      return next
    })
    try {
      for (const thread of targets) {
        await onDeleteThread(thread.id)
      }
      exitSelectMode()
    } finally {
      setDeletingThreadIds((prev) => {
        const next = { ...prev }
        for (const id of ids) delete next[id]
        return next
      })
      setBatchBusy(false)
    }
  }

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

  const handleDeleteSelected = (): void => {
    const targets = filteredChats.filter((thread) => selectedIds.has(thread.id))
    if (targets.length === 0) return
    const ok = window.confirm(t('sidebarChatsDeleteSelectedConfirm', { count: targets.length }))
    if (!ok) return
    void deleteThreads(targets)
  }

  const handleClearAll = (): void => {
    setMenuOpen(false)
    if (filteredChats.length === 0) return
    const ok = window.confirm(t('sidebarChatsClearAllConfirm', { count: filteredChats.length }))
    if (!ok) return
    setCollapsed(false)
    void deleteThreads(filteredChats)
  }

  return (
    <div className="ds-sidebar-chats-section ds-no-drag flex h-full min-h-0 flex-col">
      <div className="ds-sidebar-chats-header shrink-0">
        {selectMode ? (
          <>
            <span className="ds-sidebar-section-label min-w-0 flex-1 truncate">
              {t('sidebarChatsSelectedCount', { count: selectedIds.size })}
            </span>
            <button
              type="button"
              onClick={toggleSelectAllVisible}
              disabled={visibleChats.length === 0 || batchBusy}
              className="shrink-0 rounded-md px-1.5 py-1 text-[12px] text-ds-muted transition-colors hover:bg-ds-hover hover:text-ds-ink disabled:opacity-40"
            >
              {allVisibleSelected ? t('sidebarChatsDeselectAll') : t('sidebarChatsSelectAll')}
            </button>
            <button
              type="button"
              onClick={handleDeleteSelected}
              disabled={selectedIds.size === 0 || batchBusy}
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
              onClick={exitSelectMode}
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
              aria-expanded={!collapsed}
            >
              {collapsed ? (
                <ChevronRight className="h-3 w-3 shrink-0 text-ds-faint" strokeWidth={2} />
              ) : (
                <ChevronDown className="h-3 w-3 shrink-0 text-ds-faint" strokeWidth={2} />
              )}
              <span className="ds-sidebar-section-label min-w-0 truncate">{t('sidebarChats')}</span>
            </button>
            <button
              type="button"
              onClick={() => {
                setCollapsed(false)
                onNewChat()
              }}
              title={t('sidebarChatsNewThread')}
              aria-label={t('sidebarChatsNewThread')}
              className="shrink-0 rounded-md p-1 text-ds-faint transition-colors duration-200 hover:bg-ds-hover/70 hover:text-ds-ink"
            >
              <Plus className="h-3.5 w-3.5" strokeWidth={1.75} />
            </button>
            <div className="relative shrink-0" ref={menuRef}>
              <button
                type="button"
                onClick={() => setMenuOpen((open) => !open)}
                title={t('sidebarChatsMenu')}
                aria-label={t('sidebarChatsMenu')}
                aria-expanded={menuOpen}
                className="rounded-md p-1 text-ds-faint transition-colors duration-200 hover:bg-ds-hover/70 hover:text-ds-ink"
              >
                <MoreHorizontal className="h-3.5 w-3.5" strokeWidth={1.85} />
              </button>
              {menuOpen ? (
                <div className="ds-glass absolute right-0 top-full z-50 mt-1 w-40 overflow-hidden rounded-lg py-1">
                  <button
                    type="button"
                    disabled={filteredChats.length === 0}
                    onClick={enterSelectMode}
                    className="flex w-full items-center gap-2 px-3 py-2 text-left text-[12px] text-ds-ink hover:bg-ds-hover disabled:opacity-40"
                  >
                    <CheckSquare className="h-3.5 w-3.5 shrink-0" strokeWidth={1.85} />
                    {t('sidebarChatsBatchSelect')}
                  </button>
                  <button
                    type="button"
                    disabled={filteredChats.length === 0 || batchBusy}
                    onClick={handleClearAll}
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

      {collapsed && !selectMode ? null : (
        <div className="ds-sidebar-chats-list ds-scroll-surface min-h-0 flex-1 overflow-y-auto overscroll-contain">
          {filteredChats.length === 0 ? (
            <div className="px-2.5 py-2 text-[13px] text-ds-faint">{t('sidebarChatsEmpty')}</div>
          ) : (
            <div className="ds-sidebar-thread-list space-y-0.5 px-1.5 pb-1">
              {visibleChats.map((thread) => (
                <ThreadRow
                  key={thread.id}
                  thread={thread}
                  variant="chats"
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
                  selectionMode={selectMode}
                  selected={selectedIds.has(thread.id)}
                  onToggleSelect={() => toggleSelect(thread.id)}
                  onSelect={() => onSelectThread(thread.id)}
                  onOpenTerminal={() => void onOpenThreadTerminal(thread.id)}
                  onDelete={() => void handleDeleteThread(thread)}
                  onCompact={() => void onCompactThread(thread.id)}
                  onTogglePin={() => onTogglePin(thread.id)}
                  canCompact={activeThreadId === thread.id && !busy}
                />
              ))}
              {hasOverflow ? (
                <button
                  type="button"
                  onClick={() => setExpanded((prev) => !prev)}
                  className="ml-1 mt-0.5 rounded-md px-2 py-1 text-[13px] text-ds-faint transition-colors duration-200 hover:bg-ds-hover hover:text-ds-ink"
                >
                  {expanded
                    ? t('sidebarWorkspaceShowLess')
                    : t('sidebarChatsShowMore', {
                        count: filteredChats.length - CHATS_VISIBLE_LIMIT
                      })}
                </button>
              ) : null}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
