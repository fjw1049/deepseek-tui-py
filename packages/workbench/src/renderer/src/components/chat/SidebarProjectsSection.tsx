import type { ReactElement } from 'react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  ChevronDown,
  ChevronRight,
  LayoutGrid,
  Loader2,
  Plus,
  Trash2,
  GitFork,
  RotateCcw,
  Archive,
  Download,
  Search
} from 'lucide-react'
import type { NormalizedThread } from '../../agent/types'
import { formatRelativeTimeLargestUnit } from '../../lib/format-relative-time'
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
  onImportSession: () => void
  onSelectThread: (threadId: string) => void
  onDeleteThread: (threadId: string) => Promise<void>
  onForkThread: (threadId: string) => Promise<void>
  onResumeThread: (threadId: string) => Promise<void>
  onCompactThread: (threadId: string) => Promise<void>
  onExportThread: (threadId: string) => Promise<{ path: string } | null>
  t: (k: string, opts?: Record<string, unknown>) => string
}

type WorkspaceGroup = [string, NormalizedThread[]]

const PROJECT_AVATAR_PALETTE = [
  'bg-amber-400/18 text-amber-700 dark:text-amber-300',
  'bg-violet-400/18 text-violet-700 dark:text-violet-300',
  'bg-sky-400/18 text-sky-700 dark:text-sky-300',
  'bg-emerald-400/18 text-emerald-700 dark:text-emerald-300',
  'bg-rose-400/18 text-rose-700 dark:text-rose-300',
  'bg-orange-400/18 text-orange-700 dark:text-orange-300'
] as const

function workspaceAvatarClass(path: string): string {
  let hash = 0
  for (let i = 0; i < path.length; i += 1) {
    hash = path.charCodeAt(i) + ((hash << 5) - hash)
  }
  return PROJECT_AVATAR_PALETTE[Math.abs(hash) % PROJECT_AVATAR_PALETTE.length]
}

function workspaceAvatarGlyph(label: string): string {
  const trimmed = label.trim()
  if (!trimmed) return '#'
  const first = trimmed[0]?.toUpperCase()
  return first && /[A-Z0-9]/i.test(first) ? first : '#'
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
  onPickWorkspace,
  onRemoveWorkspace,
  onCreateThreadInWorkspace,
  onImportSession,
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
  const [searchQuery, setSearchQuery] = useState('')
  const [searchExpanded, setSearchExpanded] = useState(false)
  const searchInputRef = useRef<HTMLInputElement>(null)
  const searchOpen = searchExpanded || searchQuery.trim().length > 0

  useEffect(() => {
    if (!searchOpen) return
    searchInputRef.current?.focus()
  }, [searchOpen])

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

    return Array.from(map.entries()).sort(([pathA, listA], [pathB, listB]) => {
      const activityDiff = latestWorkspaceActivity(listB) - latestWorkspaceActivity(listA)
      if (activityDiff !== 0) return activityDiff
      return workspaceLabelFromPath(pathA).localeCompare(workspaceLabelFromPath(pathB))
    })
  }, [threads, workspaceRoot])

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

  const renderWorkspace = ([workspacePath, list]: WorkspaceGroup): ReactElement => {
    const folderName = workspaceLabelFromPath(workspacePath)
    const isCollapsed = collapsed[workspacePath] === true
    const sortedThreads = [...list].sort((a, b) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt))
    const workspaceExpanded = expandedWorkspaces[workspacePath] === true
    const hasOverflow = sortedThreads.length > 5
    const visibleThreads = workspaceExpanded ? sortedThreads : sortedThreads.slice(0, 5)

    return (
      <div key={workspacePath} className="mb-1">
        <div className="ds-sidebar-workspace group" title={workspacePath}>
          <button
            type="button"
            onClick={() =>
              setCollapsed((current) => ({ ...current, [workspacePath]: !current[workspacePath] }))
            }
            className="flex min-h-[36px] min-w-0 flex-1 items-center gap-1.5 px-2 py-1.5 text-left"
          >
            {isCollapsed ? (
              <ChevronRight className="h-3 w-3 shrink-0 text-ds-faint" strokeWidth={2} />
            ) : (
              <ChevronDown className="h-3 w-3 shrink-0 text-ds-faint" strokeWidth={2} />
            )}
            <span
              className={`ds-sidebar-project-avatar ${workspaceAvatarClass(workspacePath)}`}
              aria-hidden
            >
              {workspaceAvatarGlyph(folderName)}
            </span>
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
              visibleThreads.map((thread) => (
                <ThreadRow
                  key={thread.id}
                  thread={thread}
                  active={activeThreadId === thread.id}
                  deleting={deletingThreadIds[thread.id] === true}
                  exporting={exportingThreadIds[thread.id] === true}
                  showRunning={
                    thread.status?.trim().toLowerCase() === 'running' ||
                    (activeThreadId === thread.id && busy) ||
                    watchTurnCompletion[thread.id] === true
                  }
                  showUnread={unreadThreadIds[thread.id] === true && activeThreadId !== thread.id}
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

  return (
    <div className="ds-no-drag flex min-h-0 flex-1 flex-col px-1">
      {exportNotice ? (
        <p className="mx-1 mb-2 rounded-xl border border-emerald-200/80 bg-emerald-50/90 px-3 py-2 text-[12px] leading-5 text-emerald-950 dark:border-emerald-900/60 dark:bg-emerald-950/35 dark:text-emerald-100">
          {exportNotice}
        </p>
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
          {filteredGroups.length === 0 ? (
            groups.length === 0 ? (
              <SidebarEmpty
                runtimeReady={runtimeReady}
                hasWorkspace={!!workspaceRoot}
                onPickWorkspace={onPickWorkspace}
                t={t}
              />
            ) : (
              <div className="px-1 py-3 text-[13px] text-ds-faint">{t('sidebarSearchNoResults')}</div>
            )
          ) : (
            filteredGroups.map(renderWorkspace)
          )}
        </div>
      </div>
    </div>
  )
}

type ThreadRowProps = {
  thread: NormalizedThread
  active: boolean
  deleting: boolean
  exporting: boolean
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
  const showStatus = showRunning || showUnreadDot

  return (
    <div
      className={`group relative flex min-w-0 items-center overflow-hidden rounded-lg transition-colors duration-200 ${
        active
          ? 'bg-black/[0.05] text-ds-ink dark:bg-white/[0.06]'
          : 'hover:bg-ds-hover/45 dark:hover:bg-white/[0.035]'
      }`}
    >
      <span
        aria-hidden
        className={`absolute bottom-1.5 top-1.5 left-0 w-[2px] rounded-full transition-all duration-200 ${
          active ? 'bg-accent opacity-100' : 'opacity-0'
        }`}
      />
      <button
        type="button"
        onClick={onSelect}
        className="relative flex min-w-0 flex-1 items-center gap-1.5 px-2.5 py-2 text-left"
        disabled={deleting || exporting}
        aria-label={
          showRunning
            ? `${thread.title} — ${t('sidebarThreadRunning')}`
            : showUnreadDot
              ? `${thread.title} — ${t('sidebarThreadUnread')}`
              : thread.title
        }
      >
        {showStatus ? (
          <span className="flex w-3 shrink-0 items-center justify-center self-center">
            {showRunning ? (
              <Loader2 className="h-3 w-3 shrink-0 animate-spin text-accent" strokeWidth={2} />
            ) : (
              <span
                className="block h-1.5 w-1.5 shrink-0 rounded-full bg-accent"
                title={t('sidebarThreadUnread')}
              />
            )}
          </span>
        ) : null}
        <span
          className={[
            'ds-sidebar-thread min-w-0 flex-1 truncate',
            active || showUnreadDot ? 'ds-sidebar-thread--emphasis' : ''
          ].join(' ')}
          title={thread.title}
        >
          {thread.title}
        </span>
        <span className="ds-sidebar-thread-meta shrink-0 group-hover:hidden">
          {formatRelativeTimeLargestUnit(thread.updatedAt)}
        </span>
      </button>
      <div className="hidden shrink-0 items-center gap-0.5 pr-1 group-hover:flex group-focus-within:flex focus-within:flex">
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
