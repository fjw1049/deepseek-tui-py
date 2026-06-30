import type { ReactElement } from 'react'
import { useMemo, useState } from 'react'
import { ChevronDown, ChevronRight, SquarePen } from 'lucide-react'
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
}: SidebarChatsSectionProps): ReactElement | null {
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

  if (filteredChats.length === 0) return null

  const hasOverflow = filteredChats.length > CHATS_VISIBLE_LIMIT
  const visibleChats = expanded ? filteredChats : filteredChats.slice(0, CHATS_VISIBLE_LIMIT)

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

  return (
    <div className="ds-no-drag mt-2 shrink-0 border-t border-ds-border-muted/20 px-1 pt-2">
      <div className="ds-sidebar-projects-toolbar">
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
            // Reveal the list so the freshly created chat is visible.
            setCollapsed(false)
            onNewChat()
          }}
          title={t('sidebarChatsNewThread')}
          aria-label={t('sidebarChatsNewThread')}
          className="shrink-0 rounded-md p-1 text-ds-faint transition-colors duration-200 hover:bg-ds-hover/70 hover:text-ds-ink"
        >
          <SquarePen className="h-3.5 w-3.5" strokeWidth={1.75} />
        </button>
      </div>

      {collapsed ? null : (
      <div className="ds-sidebar-thread-list max-h-[30vh] space-y-0.5 overflow-y-auto px-1.5 pb-1">
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
              : t('sidebarChatsShowMore', { count: filteredChats.length - CHATS_VISIBLE_LIMIT })}
          </button>
        ) : null}
      </div>
      )}
    </div>
  )
}
