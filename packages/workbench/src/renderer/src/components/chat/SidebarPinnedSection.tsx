import type { ReactElement } from 'react'
import { useMemo, useState } from 'react'
import type { NormalizedThread } from '../../agent/types'
import { useThreadsWithActiveTasks } from '../../hooks/use-thread-tasks'
import { extractTasksFromBlocks } from '../../lib/extract-tasks-from-blocks'
import { useChatStore } from '../../store/chat-store'
import { isWorkspaceHidden } from '../../lib/sidebar-chrome'
import { workspaceLabelFromPath } from '../../lib/workspace-label'
import { isChatsWorkspace, normalizeWorkspaceRoot } from '../../lib/workspace-path'
import { ThreadRow } from './SidebarProjectsSection'

type SidebarPinnedSectionProps = {
  onSelectThread: (threadId: string) => void
  onOpenThreadTerminal: (threadId: string) => Promise<void>
  onDeleteThread: (threadId: string) => Promise<void>
  onCompactThread: (threadId: string) => Promise<void>
  onTogglePin: (threadId: string) => void
  t: (k: string, opts?: Record<string, unknown>) => string
}

export function SidebarPinnedSection({
  onSelectThread,
  onOpenThreadTerminal,
  onDeleteThread,
  onCompactThread,
  onTogglePin,
  t
}: SidebarPinnedSectionProps): ReactElement | null {
  const threads = useChatStore((s) => s.threads)
  const activeThreadId = useChatStore((s) => s.activeThreadId)
  const pinnedThreadIds = useChatStore((s) => s.pinnedThreadIds)
  const hiddenWorkspacePaths = useChatStore((s) => s.hiddenWorkspacePaths)
  const searchQuery = useChatStore((s) => s.sidebarSearchQuery)
  const busy = useChatStore((s) => s.busy)
  const watchTurnCompletion = useChatStore((s) => s.watchTurnCompletion)
  const unreadThreadIds = useChatStore((s) => s.unreadThreadIds)
  const activeThreadBlocks = useChatStore((s) => s.blocks)
  const { threadIds: threadsWithActiveTasks, taskIds: activeTaskIds } = useThreadsWithActiveTasks()
  const [deletingThreadIds, setDeletingThreadIds] = useState<Record<string, boolean>>({})

  const pinnedSet = useMemo(() => new Set(pinnedThreadIds), [pinnedThreadIds])

  const activeThreadHasTask = useMemo(() => {
    if (!activeThreadId) return false
    return extractTasksFromBlocks(activeThreadBlocks).some((task) => activeTaskIds.has(task.id))
  }, [activeThreadId, activeThreadBlocks, activeTaskIds])

  const pinnedThreads = useMemo(() => {
    const byId = new Map(threads.map((thread) => [thread.id, thread]))
    return pinnedThreadIds
      .map((id) => byId.get(id))
      .filter((thread): thread is NormalizedThread => {
        if (!thread) return false
        const workspace = normalizeWorkspaceRoot(thread.workspace)
        if (workspace && isWorkspaceHidden(workspace, hiddenWorkspacePaths)) return false
        return true
      })
  }, [threads, pinnedThreadIds, hiddenWorkspacePaths])

  const filteredPinnedThreads = useMemo(() => {
    const query = searchQuery.trim().toLowerCase()
    if (!query) return pinnedThreads
    return pinnedThreads.filter((thread) => thread.title.toLowerCase().includes(query))
  }, [pinnedThreads, searchQuery])

  if (filteredPinnedThreads.length === 0) return null

  const pinnedSourceLabel = (thread: NormalizedThread): string => {
    if (isChatsWorkspace(thread.workspace)) return t('sidebarChatBadge')
    return workspaceLabelFromPath(normalizeWorkspaceRoot(thread.workspace))
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

  return (
    <div className="ds-sidebar-pinned-pane ds-no-drag">
      <div className="ds-sidebar-pinned-header">
        <span className="ds-sidebar-section-label shrink-0">{t('sidebarPinned')}</span>
      </div>
      <div className="ds-sidebar-pinned-list ds-scroll-surface min-h-0 overflow-y-auto overscroll-contain">
        <div className="ds-sidebar-thread-list space-y-0.5 px-1.5 pb-1">
          {filteredPinnedThreads.map((thread) => (
            <ThreadRow
              key={thread.id}
              thread={thread}
              variant="pinned"
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
              sourceLabel={pinnedSourceLabel(thread)}
              onSelect={() => onSelectThread(thread.id)}
              onOpenTerminal={() => void onOpenThreadTerminal(thread.id)}
              onDelete={() => void handleDeleteThread(thread)}
              onCompact={() => void onCompactThread(thread.id)}
              onTogglePin={() => onTogglePin(thread.id)}
              canCompact={activeThreadId === thread.id && !busy}
            />
          ))}
        </div>
      </div>
    </div>
  )
}
