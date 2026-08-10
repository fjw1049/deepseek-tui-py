import { useEffect, useMemo, useState, type ReactElement, type MouseEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { ArrowLeft, Plus } from 'lucide-react'
import { ThreadContextMenu, type ThreadContextMenuAction } from '../chat/ThreadContextMenu'
import { useThreadsWithActiveTasks } from '../../hooks/use-thread-tasks'
import {
  copyableRelativePath,
  isWorkspaceHidden,
  threadLabelKey,
  type SidebarLabelColor
} from '../../lib/sidebar-chrome'
import { openWorkspacePathInEditor, revealWorkspacePathInFolder } from '../../lib/open-workspace-path'
import { loadProjectOrder } from '../../lib/sidebar-manual-order'
import { loadProjectSortMode } from '../../lib/sidebar-project-sort'
import { deriveThreadTitleFromPrompt } from '../../lib/thread-title'
import { workspaceLabelFromPath } from '../../lib/workspace-label'
import {
  isChatsWorkspace,
  normalizeWorkspaceRoot
} from '../../lib/workspace-path'
import { useChatStore } from '../../store/chat-store'
import {
  clearKanbanDraftPrompt,
  loadKanbanDraftOrders,
  loadKanbanDraftPrompts,
  loadKanbanDrafts,
  setKanbanDraftOrder,
  setKanbanDraftPrompt
} from './kanban-ui-store'
import { KanbanNewTaskDialog, type KanbanNewTaskSubmit } from './KanbanNewTaskDialog'
import { KanbanOverview } from './KanbanOverview'
import { KanbanProjectBoardView } from './KanbanProjectBoardView'
import {
  buildKanbanBoard,
  CHATS_COLUMN_ID,
  withProjectBranches,
  type KanbanCard,
  type KanbanProjectBoard
} from './kanban.logic'

type Props = {
  onOpenThread: (threadId: string) => void
  onOpenThreadTerminal: (threadId: string) => Promise<void>
}

type MenuState = {
  card: KanbanCard
  x: number
  y: number
}

type RenameState = {
  threadId: string
  title: string
}

export function KanbanView({ onOpenThread, onOpenThreadTerminal }: Props): ReactElement {
  const { t } = useTranslation('common')
  const threads = useChatStore((s) => s.threads)
  const workspaceRoot = useChatStore((s) => s.workspaceRoot)
  const hiddenWorkspacePaths = useChatStore((s) => s.hiddenWorkspacePaths)
  const watchTurnCompletion = useChatStore((s) => s.watchTurnCompletion)
  const activeThreadId = useChatStore((s) => s.activeThreadId)
  const busy = useChatStore((s) => s.busy)
  const unreadThreadIds = useChatStore((s) => s.unreadThreadIds)
  const pinnedThreadIds = useChatStore((s) => s.pinnedThreadIds)
  const runtimeReady = useChatStore((s) => s.runtimeConnection === 'ready')
  const createThread = useChatStore((s) => s.createThread)
  const sendMessage = useChatStore((s) => s.sendMessage)
  const setComposerModel = useChatStore((s) => s.setComposerModel)
  const selectThread = useChatStore((s) => s.selectThread)
  const renameThread = useChatStore((s) => s.renameThread)
  const deleteThread = useChatStore((s) => s.deleteThread)
  const archiveThread = useChatStore((s) => s.archiveThread)
  const togglePin = useChatStore((s) => s.togglePin)
  const markThreadUnread = useChatStore((s) => s.markThreadUnread)
  const sidebarLabelColors = useChatStore((s) => s.sidebarLabelColors)
  const setSidebarLabelColor = useChatStore((s) => s.setSidebarLabelColor)
  const { threadIds: threadsWithActiveTasks } = useThreadsWithActiveTasks()

  const [projectOrder] = useState(() => loadProjectOrder())
  const [projectSortMode] = useState(() => loadProjectSortMode())
  const [draftPrompts, setDraftPrompts] = useState(() => loadKanbanDraftPrompts())
  const [draftOrders, setDraftOrders] = useState(() => loadKanbanDraftOrders())
  const [optimisticInProgress, setOptimisticInProgress] = useState<Set<string>>(() => new Set())
  const [branchByProjectId, setBranchByProjectId] = useState<Map<string, string | null>>(
    () => new Map()
  )
  const [activeProjectId, setActiveProjectId] = useState<string | null>(null)
  const [newTaskDialog, setNewTaskDialog] = useState<{
    projectId: string | null
    sendAsDraft: boolean
  } | null>(null)
  const [submittingTask, setSubmittingTask] = useState(false)
  const [menu, setMenu] = useState<MenuState | null>(null)
  const [rename, setRename] = useState<RenameState | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const inProgressThreadIds = useMemo(() => {
    const ids = new Set<string>()
    for (const id of Object.keys(watchTurnCompletion)) {
      if (watchTurnCompletion[id]) ids.add(id)
    }
    for (const id of threadsWithActiveTasks) ids.add(id)
    if (busy && activeThreadId) ids.add(activeThreadId)
    return ids
  }, [activeThreadId, busy, threadsWithActiveTasks, watchTurnCompletion])

  // Clear optimistic overlays once runtime/state catches up.
  useEffect(() => {
    if (optimisticInProgress.size === 0) return
    setOptimisticInProgress((prev) => {
      let changed = false
      const next = new Set(prev)
      for (const id of prev) {
        if (inProgressThreadIds.has(id)) {
          next.delete(id)
          changed = true
        }
      }
      return changed ? next : prev
    })
  }, [inProgressThreadIds, optimisticInProgress.size])

  const baseBoard = useMemo(
    () =>
      buildKanbanBoard({
        threads,
        hiddenWorkspacePaths,
        projectOrder,
        projectSortMode,
        inProgressThreadIds,
        chatsColumnName: t('kanbanChatsColumn'),
        draftPromptByThreadId: draftPrompts,
        draftOrderByProjectId: draftOrders,
        optimisticInProgressThreadIds: optimisticInProgress
      }),
    [
      threads,
      hiddenWorkspacePaths,
      projectOrder,
      projectSortMode,
      inProgressThreadIds,
      t,
      draftPrompts,
      draftOrders,
      optimisticInProgress
    ]
  )

  const projectPathsKey = useMemo(
    () =>
      baseBoard.projects
        .map((project) => project.workspacePath)
        .filter((path): path is string => Boolean(path))
        .join('\0'),
    [baseBoard.projects]
  )

  useEffect(() => {
    const paths = projectPathsKey ? projectPathsKey.split('\0') : []
    if (paths.length === 0 || typeof window.dsGui?.getGitBranches !== 'function') {
      setBranchByProjectId(new Map())
      return
    }
    let cancelled = false
    void (async () => {
      const next = new Map<string, string | null>()
      await Promise.all(
        paths.map(async (path) => {
          try {
            const result = await window.dsGui.getGitBranches(path)
            next.set(path, result.ok ? result.currentBranch : null)
          } catch {
            next.set(path, null)
          }
        })
      )
      if (!cancelled) setBranchByProjectId(next)
    })()
    return () => {
      cancelled = true
    }
  }, [projectPathsKey])

  const board = useMemo(
    () => withProjectBranches(baseBoard, branchByProjectId),
    [baseBoard, branchByProjectId]
  )

  /** Board columns omit empty projects; the New Task picker still offers them. */
  const newTaskProjects = useMemo(() => {
    const byId = new Map(
      board.projects.map((project) => [
        project.projectId,
        {
          projectId: project.projectId,
          projectName: project.projectName,
          workspacePath: project.workspacePath
        }
      ])
    )
    const candidates = [
      ...projectOrder,
      normalizeWorkspaceRoot(workspaceRoot)
    ]
    for (const path of candidates) {
      const key = normalizeWorkspaceRoot(path)
      if (!key || isChatsWorkspace(key) || isWorkspaceHidden(key, hiddenWorkspacePaths)) continue
      if (byId.has(key)) continue
      byId.set(key, {
        projectId: key,
        projectName: workspaceLabelFromPath(key),
        workspacePath: key
      })
    }
    return [...byId.values()]
  }, [board.projects, projectOrder, workspaceRoot, hiddenWorkspacePaths])

  const projectBoard =
    activeProjectId == null
      ? null
      : (board.projects.find((project) => project.projectId === activeProjectId) ?? null)

  useEffect(() => {
    if (activeProjectId && !projectBoard) setActiveProjectId(null)
  }, [activeProjectId, projectBoard])

  const showNotice = (message: string): void => {
    setNotice(message)
    window.setTimeout(() => setNotice(null), 2400)
  }

  const handleOpenCard = (card: KanbanCard): void => {
    onOpenThread(card.threadId)
  }

  const openNewTask = (projectId: string | null, sendAsDraft = false): void => {
    setNewTaskDialog({ projectId, sendAsDraft })
  }

  const ensureThreadForProject = async (project: {
    projectId: string
    workspacePath: string | null
  }): Promise<string | null> => {
    if (!runtimeReady) {
      showNotice(t('runtimeActionNeedsConnection'))
      return null
    }
    if (project.projectId === CHATS_COLUMN_ID || !project.workspacePath) {
      await createThread({ chats: true })
    } else {
      await createThread({ workspaceRoot: project.workspacePath })
    }
    return useChatStore.getState().activeThreadId
  }

  const handleNewTaskSubmit = async (input: KanbanNewTaskSubmit): Promise<void> => {
    setSubmittingTask(true)
    try {
      if (input.model.trim()) setComposerModel(input.model.trim())
      const threadId = await ensureThreadForProject(input)
      if (!threadId) return
      if (input.sendAsDraft) {
        setKanbanDraftPrompt(threadId, input.prompt, input.model)
        setDraftPrompts(loadKanbanDraftPrompts())
        const title = deriveThreadTitleFromPrompt(input.prompt)
        await renameThread(threadId, title)
        setNewTaskDialog(null)
        showNotice(t('kanbanDraftSaved'))
        return
      }
      clearKanbanDraftPrompt(threadId)
      setDraftPrompts(loadKanbanDraftPrompts())
      setOptimisticInProgress((prev) => new Set(prev).add(threadId))
      const sent = await sendMessage(input.prompt)
      if (!sent) {
        setOptimisticInProgress((prev) => {
          const next = new Set(prev)
          next.delete(threadId)
          return next
        })
        showNotice(t('kanbanSendFailed'))
        return
      }
      setNewTaskDialog(null)
    } finally {
      setSubmittingTask(false)
    }
  }

  const handleDispatchDraft = async (card: KanbanCard): Promise<void> => {
    if (!card.draftPrompt.trim()) {
      showNotice(t('kanbanDispatchOpenChat'))
      onOpenThread(card.threadId)
      return
    }
    if (!runtimeReady) {
      showNotice(t('runtimeActionNeedsConnection'))
      return
    }
    const stored = loadKanbanDrafts()[card.threadId]
    if (stored?.model?.trim()) setComposerModel(stored.model.trim())
    await selectThread(card.threadId)
    setOptimisticInProgress((prev) => new Set(prev).add(card.threadId))
    const prompt = card.draftPrompt
    const model = stored?.model
    clearKanbanDraftPrompt(card.threadId)
    setDraftPrompts(loadKanbanDraftPrompts())
    const sent = await sendMessage(prompt)
    if (!sent) {
      setKanbanDraftPrompt(card.threadId, prompt, model)
      setDraftPrompts(loadKanbanDraftPrompts())
      setOptimisticInProgress((prev) => {
        const next = new Set(prev)
        next.delete(card.threadId)
        return next
      })
      showNotice(t('kanbanSendFailed'))
      return
    }
    showNotice(t('kanbanDraftSent'))
  }

  const handleReorderDrafts = (projectId: string, cardIds: string[]): void => {
    setKanbanDraftOrder(projectId, cardIds)
    setDraftOrders(loadKanbanDraftOrders())
  }

  const handleCardContextMenu = (card: KanbanCard, event: MouseEvent): void => {
    event.preventDefault()
    event.stopPropagation()
    setMenu({ card, x: event.clientX, y: event.clientY })
  }

  const menuThread = menu
    ? threads.find((thread) => thread.id === menu.card.threadId) ?? null
    : null
  const menuPath = menuThread
    ? isChatsWorkspace(menuThread.workspace)
      ? ''
      : normalizeWorkspaceRoot(menuThread.workspace)
    : ''

  const handleMenuAction = (action: ThreadContextMenuAction): void => {
    if (!menu) return
    const threadId = menu.card.threadId
    const thread = threads.find((item) => item.id === threadId)
    const path = thread
      ? isChatsWorkspace(thread.workspace)
        ? ''
        : normalizeWorkspaceRoot(thread.workspace)
      : ''
    switch (action) {
      case 'rename':
        setRename({ threadId, title: thread?.title ?? menu.card.title })
        break
      case 'toggle-pin':
        togglePin(threadId)
        break
      case 'archive':
        void archiveThread(threadId)
        clearKanbanDraftPrompt(threadId)
        setDraftPrompts(loadKanbanDraftPrompts())
        break
      case 'mark-unread':
        markThreadUnread(threadId)
        break
      case 'copy-path':
        if (path) void navigator.clipboard?.writeText(path)
        break
      case 'copy-relative-path':
        if (path) void navigator.clipboard?.writeText(copyableRelativePath(path, path))
        break
      case 'open-with-editor':
        if (path) void openWorkspacePathInEditor({ path }, path)
        break
      case 'reveal-in-folder':
        if (path) void revealWorkspacePathInFolder(path)
        break
      case 'open-terminal':
        void onOpenThreadTerminal(threadId)
        break
      case 'copy-thread-id':
        void navigator.clipboard?.writeText(threadId)
        break
      case 'delete': {
        const title = thread?.title ?? menu.card.title
        if (!window.confirm(t('sidebarThreadDeleteConfirm', { title }))) break
        void deleteThread(threadId)
        clearKanbanDraftPrompt(threadId)
        setDraftPrompts(loadKanbanDraftPrompts())
        break
      }
    }
    setMenu(null)
  }

  const commitRename = async (): Promise<void> => {
    if (!rename) return
    const next = rename.title.trim()
    if (next) await renameThread(rename.threadId, next)
    setRename(null)
  }

  const headerCount = projectBoard?.totalCount ?? board.totalCount
  const headerTitle = projectBoard?.projectName ?? t('kanbanTitle')

  return (
    <div className="ds-no-drag flex h-full min-h-0 flex-col bg-transparent">
      <header className="flex shrink-0 items-center justify-between gap-3 px-5 pb-3 pt-4">
        <div className="flex min-w-0 items-center gap-2">
          {projectBoard ? (
            <button
              type="button"
              onClick={() => setActiveProjectId(null)}
              className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-ds-faint transition hover:bg-ds-hover hover:text-ds-ink"
              aria-label={t('kanbanBackToOverview')}
              title={t('kanbanBackToOverview')}
            >
              <ArrowLeft className="h-4 w-4" strokeWidth={1.9} />
            </button>
          ) : null}
          <div className="flex min-w-0 items-baseline gap-2">
            <h1 className="truncate text-[15px] font-semibold text-ds-ink">{headerTitle}</h1>
            <span className="shrink-0 text-[12px] text-ds-faint">
              {t('kanbanTaskCount', { count: headerCount })}
            </span>
          </div>
        </div>
        <button
          type="button"
          onClick={() =>
            openNewTask(projectBoard?.projectId ?? null, false)
          }
          className="inline-flex items-center gap-1.5 rounded-lg border border-ds-border bg-ds-card px-2.5 py-1.5 text-[12px] font-medium text-ds-ink transition hover:bg-ds-hover"
        >
          <Plus className="h-3.5 w-3.5" strokeWidth={2} />
          {t('kanbanNewTask')}
        </button>
      </header>

      {notice ? (
        <div className="px-5 pb-2 text-[12px] text-ds-muted">{notice}</div>
      ) : null}

      <div className="min-h-0 flex-1">
        {projectBoard ? (
          <KanbanProjectBoardView
            board={projectBoard}
            onOpenCard={handleOpenCard}
            onCardContextMenu={handleCardContextMenu}
            onNewTask={() => openNewTask(projectBoard.projectId, true)}
            onReorderDrafts={(cardIds) => handleReorderDrafts(projectBoard.projectId, cardIds)}
            onDispatchDraft={handleDispatchDraft}
          />
        ) : (
          <KanbanOverview
            board={board}
            onOpenProject={setActiveProjectId}
            onOpenCard={handleOpenCard}
            onCardContextMenu={handleCardContextMenu}
            onNewTask={(project: KanbanProjectBoard) => openNewTask(project.projectId, false)}
          />
        )}
      </div>

      <KanbanNewTaskDialog
        open={newTaskDialog != null}
        projects={newTaskProjects}
        initialProjectId={newTaskDialog?.projectId ?? null}
        initialSendAsDraft={newTaskDialog?.sendAsDraft ?? false}
        submitting={submittingTask}
        onClose={() => setNewTaskDialog(null)}
        onSubmit={handleNewTaskSubmit}
      />

      {menu && menuThread ? (
        <ThreadContextMenu
          x={menu.x}
          y={menu.y}
          pinned={pinnedThreadIds.includes(menu.card.threadId)}
          canMarkUnread={!unreadThreadIds[menu.card.threadId]}
          hasPath={menuPath.length > 0}
          labelColor={(sidebarLabelColors[threadLabelKey(menu.card.threadId)] ??
            null) as SidebarLabelColor}
          onLabelColorChange={(color) =>
            setSidebarLabelColor(threadLabelKey(menu.card.threadId), color)
          }
          onAction={handleMenuAction}
          onClose={() => setMenu(null)}
          t={t}
        />
      ) : null}

      {rename ? (
        <div className="fixed inset-0 z-[210] flex items-center justify-center bg-black/45 p-4">
          <div className="w-full max-w-sm rounded-xl border border-ds-border bg-ds-elevated p-4 shadow-panel">
            <div className="mb-3 text-[13px] font-medium text-ds-ink">{t('kanbanRenameTitle')}</div>
            <input
              value={rename.title}
              onChange={(event) => setRename({ ...rename, title: event.target.value })}
              onKeyDown={(event) => {
                if (event.key === 'Enter') void commitRename()
                if (event.key === 'Escape') setRename(null)
              }}
              className="w-full rounded-lg border border-ds-border bg-ds-card px-3 py-2 text-[13px] text-ds-ink outline-none focus:ring-1 focus:ring-sky-500/40"
              autoFocus
            />
            <div className="mt-3 flex justify-end gap-2">
              <button
                type="button"
                className="rounded-lg px-3 py-1.5 text-[12px] text-ds-muted hover:bg-ds-hover"
                onClick={() => setRename(null)}
              >
                {t('kanbanDialogCancel')}
              </button>
              <button
                type="button"
                className="rounded-lg bg-sky-600 px-3 py-1.5 text-[12px] font-medium text-white hover:bg-sky-500"
                onClick={() => void commitRename()}
              >
                {t('kanbanRenameSave')}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
