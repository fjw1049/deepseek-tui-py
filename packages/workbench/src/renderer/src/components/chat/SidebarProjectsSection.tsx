import type { ReactElement } from 'react'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  ChevronDown,
  ChevronRight,
  Folder,
  FolderOpen,
  LayoutGrid,
  Loader2,
  MessageSquare,
  Plus,
  Trash2,
  GitFork,
  RotateCcw,
  Archive,
  Download
} from 'lucide-react'
import type { NormalizedThread } from '../../agent/types'
import { formatRelativeTime } from '../../lib/format-relative-time'
import { workspaceLabelFromPath } from '../../lib/workspace-label'
import { isClawWorkspacePath, isInternalTemporaryWorkspace, normalizeWorkspaceRoot } from '../../lib/workspace-path'

type SidebarProjectsSectionProps = {
  threads: NormalizedThread[]
  activeThreadId: string | null
  runtimeReady: boolean
  workspaceRoot: string
  busy: boolean
  watchTurnCompletion: Record<string, boolean>
  unreadThreadIds: Record<string, boolean>
  locale: string
  onPickWorkspace: () => void
  onRemoveWorkspace: (workspacePath: string) => Promise<void>
  onCreateThreadInWorkspace: (workspacePath: string) => void
  onSelectThread: (threadId: string) => void
  onDeleteThread: (threadId: string) => Promise<void>
  onForkThread: (threadId: string) => Promise<void>
  onResumeThread: (threadId: string) => Promise<void>
  onCompactThread: (threadId: string) => Promise<void>
  onExportThread: (threadId: string) => Promise<{ path: string } | null>
  t: (k: string, opts?: Record<string, unknown>) => string
}

export function SidebarProjectsSection({
  threads,
  activeThreadId,
  runtimeReady,
  workspaceRoot,
  busy,
  watchTurnCompletion,
  unreadThreadIds,
  locale,
  onPickWorkspace,
  onRemoveWorkspace,
  onCreateThreadInWorkspace,
  onSelectThread,
  onDeleteThread,
  onForkThread,
  onResumeThread,
  onCompactThread,
  onExportThread,
  t
}: SidebarProjectsSectionProps): ReactElement {
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})
  const [expandedWorkspaces, setExpandedWorkspaces] = useState<Record<string, boolean>>({})
  const [deletingThreadIds, setDeletingThreadIds] = useState<Record<string, boolean>>({})
  const [exportingThreadIds, setExportingThreadIds] = useState<Record<string, boolean>>({})
  const [exportNotice, setExportNotice] = useState<string | null>(null)

  const groups = useMemo(() => {
    const map = new Map<string, NormalizedThread[]>()
    const selectedWorkspace = normalizeWorkspaceRoot(workspaceRoot)

    for (const th of threads) {
      if (isInternalTemporaryWorkspace(th.workspace)) continue
      if (isClawWorkspacePath(th.workspace)) continue
      const key = normalizeWorkspaceRoot(th.workspace)
      if (!key) continue
      const arr = map.get(key) ?? []
      arr.push(th)
      map.set(key, arr)
    }

    if (selectedWorkspace && !map.has(selectedWorkspace)) {
      map.set(selectedWorkspace, [])
    }

    return Array.from(map.entries()).sort(([a], [b]) => {
      if (a === selectedWorkspace && b !== selectedWorkspace) return -1
      if (b === selectedWorkspace && a !== selectedWorkspace) return 1
      return a.localeCompare(b)
    })
  }, [threads, workspaceRoot])

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

  const handleExportThread = async (threadId: string): Promise<void> => {
    const trimmed = threadId.trim()
    if (!trimmed || exportingThreadIds[trimmed] || deletingThreadIds[trimmed]) return
    setExportingThreadIds((prev) => ({ ...prev, [trimmed]: true }))
    setExportNotice(null)
    try {
      const result = await onExportThread(trimmed)
      if (result?.path) {
        setExportNotice(t('exportSessionSuccess', { path: result.path }))
      }
    } finally {
      setExportingThreadIds((prev) => {
        const next = { ...prev }
        delete next[trimmed]
        return next
      })
    }
  }

  return (
    <div className="ds-no-drag flex min-h-0 flex-1 flex-col">
      {exportNotice ? (
        <p className="mx-2 mb-2 rounded-xl border border-emerald-200/80 bg-emerald-50/90 px-3 py-2 text-[12px] leading-5 text-emerald-950 dark:border-emerald-900/60 dark:bg-emerald-950/35 dark:text-emerald-100">
          {exportNotice}
        </p>
      ) : null}
      <div className="flex items-center justify-between px-2 pb-1.5 pt-1">
        <span className="ds-sidebar-section-label">{t('sidebarProjects')}</span>
        <div className="flex items-center gap-0.5">
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

      <div className="min-h-0 flex-1 overflow-y-auto px-0.5 pb-1">
        {groups.length === 0 ? (
          <SidebarEmpty
            runtimeReady={runtimeReady}
            hasWorkspace={!!workspaceRoot}
            onPickWorkspace={onPickWorkspace}
            t={t}
          />
        ) : null}

        {groups.map(([workspacePath, list]) => {
          const folderName = workspaceLabelFromPath(workspacePath)
          const isCollapsed = collapsed[workspacePath] === true
          const sortedThreads = [...list].sort(
            (a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt)
          )
          const workspaceExpanded = expandedWorkspaces[workspacePath] === true
          const hasOverflow = sortedThreads.length > 5
          const visibleThreads = workspaceExpanded
            ? sortedThreads
            : sortedThreads.slice(0, 5)
          return (
            <div key={workspacePath} className="mb-1">
              <div className="ds-sidebar-workspace group" title={workspacePath}>
                <button
                  type="button"
                  onClick={() =>
                    setCollapsed((current) => ({ ...current, [workspacePath]: !current[workspacePath] }))
                  }
                  className="flex min-w-0 flex-1 items-center gap-1.5 px-2 py-1.5 text-left"
                >
                  {isCollapsed ? (
                    <ChevronRight className="h-3 w-3 shrink-0 text-ds-faint" strokeWidth={2} />
                  ) : (
                    <ChevronDown className="h-3 w-3 shrink-0 text-ds-faint" strokeWidth={2} />
                  )}
                  {isCollapsed ? (
                    <Folder className="h-3.5 w-3.5 shrink-0 text-ds-muted" strokeWidth={1.75} />
                  ) : (
                    <FolderOpen className="h-3.5 w-3.5 shrink-0 text-ds-muted" strokeWidth={1.75} />
                  )}
                  <span className="min-w-0 flex-1 truncate">{folderName}</span>
                </button>
                <button
                  type="button"
                  onClick={(event) => {
                    event.stopPropagation()
                    onCreateThreadInWorkspace(workspacePath)
                  }}
                  className="shrink-0 rounded-md p-1 text-ds-faint opacity-45 transition-all duration-200 hover:bg-ds-hover/80 hover:text-ds-ink hover:opacity-100 group-hover:opacity-100 focus-visible:opacity-100"
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
                  className="mr-1 shrink-0 rounded-md p-1 text-ds-faint opacity-45 transition-all duration-200 hover:bg-ds-hover/80 hover:text-red-500 hover:opacity-100 group-hover:opacity-100 focus-visible:opacity-100"
                  title={t('sidebarWorkspaceRemove')}
                  aria-label={t('sidebarWorkspaceRemove')}
                >
                  <Trash2 className="h-3.5 w-3.5" strokeWidth={1.9} />
                </button>
              </div>

              {!isCollapsed ? (
                <div className="mt-0.5 space-y-0.5 pl-2">
                  {sortedThreads.length === 0 ? (
                    <div className="flex items-center justify-between gap-2 px-2 py-1">
                      <div className="text-[13.5px] leading-5 text-ds-faint">
                        {t('sidebarWorkspaceEmpty')}
                      </div>
                      <button
                        type="button"
                        onClick={() => onCreateThreadInWorkspace(workspacePath)}
                        className="shrink-0 rounded-md px-2 py-1 text-[13px] font-medium text-ds-faint transition-colors duration-200 hover:bg-ds-hover hover:text-ds-ink"
                      >
                        {t('sidebarWorkspaceNewThread')}
                      </button>
                    </div>
                  ) : (
                    visibleThreads.map((thread) => (
                      <ThreadRow
                        key={thread.id}
                        thread={thread}
                        active={activeThreadId === thread.id}
                        deleting={deletingThreadIds[thread.id] === true}
                        exporting={exportingThreadIds[thread.id] === true}
                        locale={locale}
                        showRunning={
                          thread.status?.trim().toLowerCase() === 'running' ||
                          (activeThreadId === thread.id && busy) ||
                          watchTurnCompletion[thread.id] === true
                        }
                        showUnread={
                          unreadThreadIds[thread.id] === true && activeThreadId !== thread.id
                        }
                        onSelect={() => onSelectThread(thread.id)}
                        onDelete={() => void handleDeleteThread(thread)}
                        onFork={() => void onForkThread(thread.id)}
                        onResume={() => void onResumeThread(thread.id)}
                        onCompact={() => void onCompactThread(thread.id)}
                        onExport={() => void handleExportThread(thread.id)}
                        canCompact={activeThreadId === thread.id && !busy}
                      />
                    ))
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
                      className="ml-1 mt-0.5 rounded-md px-2 py-1 text-[13.5px] text-ds-faint transition-colors duration-200 hover:bg-ds-hover hover:text-ds-ink"
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
        })}
      </div>
    </div>
  )
}

type ThreadRowProps = {
  thread: NormalizedThread
  active: boolean
  deleting: boolean
  exporting: boolean
  locale: string
  showRunning: boolean
  showUnread: boolean
  canCompact: boolean
  onSelect: () => void
  onDelete: () => void
  onFork: () => void
  onResume: () => void
  onCompact: () => void
  onExport: () => void
}

function ThreadRow({
  thread,
  active,
  deleting,
  exporting,
  locale,
  showRunning,
  showUnread,
  canCompact,
  onSelect,
  onDelete,
  onFork,
  onResume,
  onCompact,
  onExport
}: ThreadRowProps): ReactElement {
  const { t } = useTranslation('common')
  const showUnreadDot = showUnread && !showRunning

  return (
    <div
      className={`group relative w-full overflow-hidden rounded-[10px] transition-colors duration-200 ${
        active
          ? 'bg-black/8 text-ds-ink dark:bg-white/[0.055]'
          : 'hover:bg-ds-hover/50 dark:hover:bg-white/[0.04]'
      }`}
    >
      <span
        aria-hidden
        className={`absolute bottom-1 top-1 left-0 w-[2px] rounded-full transition-all duration-200 ${
          active ? 'bg-accent opacity-100' : 'bg-transparent opacity-0'
        }`}
      />
      <button
        type="button"
        onClick={onSelect}
        className="flex w-full items-center gap-1.5 px-3 py-2 pr-[5.5rem] text-left"
        disabled={deleting || exporting}
        aria-label={
          showRunning
            ? `${thread.title} — ${t('sidebarThreadRunning')}`
            : showUnreadDot
              ? `${thread.title} — ${t('sidebarThreadUnread')}`
              : thread.title
        }
      >
        <span
          className="flex w-4 shrink-0 flex-col items-center justify-center self-center"
          aria-hidden={!showRunning && !showUnreadDot}
        >
          {showRunning ? (
            <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-accent" strokeWidth={2} />
          ) : showUnreadDot ? (
            <span
              className="block h-2 w-2 shrink-0 rounded-full bg-accent shadow-[0_0_0_1px_rgba(79,124,255,0.2)]"
              title={t('sidebarThreadUnread')}
            />
          ) : null}
        </span>
        <MessageSquare
          className={`h-3.5 w-3.5 shrink-0 ${active ? 'text-accent' : 'text-ds-faint/90'}`}
          strokeWidth={1.8}
        />
        <span
          className={`ds-sidebar-thread min-w-0 flex-1 truncate ${
            showUnreadDot && !active ? 'font-semibold' : ''
          }`}
          title={thread.title}
        >
          {thread.title}
        </span>
        <span className="ds-sidebar-thread-meta shrink-0 transition-opacity duration-200 group-hover:opacity-0">
          {formatRelativeTime(thread.updatedAt, locale)}
        </span>
      </button>
      <div className="absolute right-1 top-1/2 flex -translate-y-1/2 items-center gap-0.5 opacity-0 transition-opacity duration-200 group-hover:opacity-100 focus-within:opacity-100">
        {canCompact ? (
          <button
            type="button"
            onClick={(event) => {
              event.stopPropagation()
              onCompact()
            }}
            disabled={deleting || exporting}
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
            onResume()
          }}
          disabled={deleting || exporting}
          className="flex h-6 w-6 items-center justify-center rounded-md text-ds-faint transition-colors duration-200 hover:bg-ds-hover hover:text-ds-ink"
          title={t('sidebarThreadResume')}
          aria-label={t('sidebarThreadResume')}
        >
          <RotateCcw className="h-3.5 w-3.5" strokeWidth={1.9} />
        </button>
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation()
            onFork()
          }}
          disabled={deleting || exporting}
          className="flex h-6 w-6 items-center justify-center rounded-md text-ds-faint transition-colors duration-200 hover:bg-ds-hover hover:text-ds-ink"
          title={t('sidebarThreadFork')}
          aria-label={t('sidebarThreadFork')}
        >
          <GitFork className="h-3.5 w-3.5" strokeWidth={1.9} />
        </button>
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation()
            onExport()
          }}
          disabled={deleting || exporting}
          className="flex h-6 w-6 items-center justify-center rounded-md text-ds-faint transition-colors duration-200 hover:bg-ds-hover hover:text-ds-ink"
          title={t('sidebarThreadExport')}
          aria-label={t('sidebarThreadExport')}
        >
          {exporting ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={2} />
          ) : (
            <Download className="h-3.5 w-3.5" strokeWidth={1.9} />
          )}
        </button>
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation()
            onDelete()
          }}
          disabled={deleting || exporting}
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
        <span className="min-w-0 flex-1 truncate">
          {t('selectWorkspace')}
        </span>
      </button>
    )
  }

  return (
    <div className="mx-2 mt-2 rounded-lg px-2 py-2">
      <p className="text-[16px] font-semibold text-ds-ink">{t('sidebarEmptyTitle')}</p>
      <p className="mt-1.5 text-[14px] leading-5 text-ds-muted">
        {runtimeReady ? t('sidebarEmptySub') : t('sidebarEmptySubOffline')}
      </p>
    </div>
  )
}
