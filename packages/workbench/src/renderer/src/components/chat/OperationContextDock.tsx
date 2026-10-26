import { preloadIdeWorkspace } from '../ide/IdeWorkspaceLayout'
import {
  useCallback,
  useMemo,
  useEffect,
  useSyncExternalStore,
  useState,
  type ReactElement
} from 'react'
import {
  Check,
  ChevronRight,
  Minimize,
  Maximize,
  GitBranch,
  GitGraph,
  ListTodo,
  PanelsTopLeft,
  FileEdit,
  FolderOpen,
  Globe2
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useShallow } from 'zustand/react/shallow'
import { ChangeDiffStatsLabel } from '../ChangeDiffStatsLabel'
import { useGitBranches } from '../../hooks/use-git-branches'
import { extractSubagentsFromBlocks } from '../../lib/extract-subagents-from-blocks'
import { openRunPanel } from '../../store/run-panel-store'
import { useLiveTasks } from '../../hooks/use-thread-tasks'
import {
  useGitBranchCompareBase,
  useGitWorkingChanges
} from '../../hooks/use-git-working-changes'
import { useWorkspaceDirtyGitRefresh } from '../../hooks/use-workspace-dirty-git-refresh'
import {
  collectWorkspaceChangeEntries,
  sumWorkspaceChangeStats
} from '../../lib/workspace-change-stats'
import { extractTasksFromBlocks } from '../../lib/extract-tasks-from-blocks'
import { extractTodosFromBlocks } from '../../lib/extract-todos-from-blocks'
import {
  resolveThreadFilesystemRoot,
  resolveThreadGitActionRoot
} from '../../lib/workspace-path'
import { workspaceLabelFromPath } from '../../lib/workspace-label'
import { useChatStore } from '../../store/chat-store'
import { GitBranchPicker } from './GitBranchPicker'
import { TaskActivity } from './TaskActivity'

type Props = {
  forceCompact?: boolean
  onExpandRequested?: () => void
  onCollapse?: () => void
  /** Project currently rendered by the owning Workbench. */
  workspaceRoot: string
  onOpenChanges?: () => void
  /** Open the right-sidebar file tree (文件 tab) — collapsed-rail files entry. */
  onOpenFilesSidebar: () => void
  /** Enter IDE/editor layout — EditView row entry. */
  onEnterIdeMode?: () => void
  previewActive: boolean
  previewEnabled: boolean
  onTogglePreview: () => void
}

const DOCK_ROW_CLASS =
  'group flex w-full items-center gap-2.5 rounded-[10px] px-1.5 py-1.5 text-left text-[13px] font-semibold leading-5 transition-colors'

/** Same horizontal inset / gap as dock rows so icon and label columns line up. */
const DOCK_SECTION_HEADER_CLASS =
  'group flex w-full items-center gap-2.5 rounded-[10px] px-1.5 py-1.5 text-left text-ds-muted transition-colors hover:text-ds-ink'

const DOCK_COMPACT_STORAGE_KEY = 'deepseekgui.operationDock.compact'
const DOCK_COMPACT_EVENT = 'deepseekgui:operation-dock-compact'
const unsavedCompact = new Map<string, boolean>()

function useDockCompact(threadId: string | null, workspaceRoot: string): [boolean, (value: boolean) => void] {
  // A draft belongs to its workspace; saved conversations have their own identity.
  const key = `${DOCK_COMPACT_STORAGE_KEY}:${JSON.stringify(threadId ? ['thread', threadId] : ['draft', workspaceRoot])}`
  const subscribe = useCallback((notify: () => void) => {
    window.addEventListener(DOCK_COMPACT_EVENT, notify)
    window.addEventListener('storage', notify)
    return () => {
      window.removeEventListener(DOCK_COMPACT_EVENT, notify)
      window.removeEventListener('storage', notify)
    }
  }, [])
  const getSnapshot = useCallback(() => {
    if (unsavedCompact.has(key)) return unsavedCompact.get(key)!
    try {
      return window.localStorage.getItem(key) === 'true'
    } catch {
      return false
    }
  }, [key])
  const compact = useSyncExternalStore(subscribe, getSnapshot)
  const setCompact = useCallback((value: boolean) => {
    try {
      window.localStorage.setItem(key, String(value))
      unsavedCompact.delete(key)
    } catch {
      // Keep the control usable when local storage is unavailable.
      unsavedCompact.set(key, value)
    }
    window.dispatchEvent(new Event(DOCK_COMPACT_EVENT))
  }, [key])
  return [compact, setCompact]
}

const ROW_ICON_TINTS = {
  violet: 'bg-violet-500/10 text-violet-500 group-hover:bg-violet-500/16 dark:text-violet-300',
  sky: 'bg-sky-500/10 text-sky-500 group-hover:bg-sky-500/16 dark:text-sky-300',
  amber: 'bg-amber-500/12 text-amber-600 group-hover:bg-amber-500/18 dark:text-amber-300',
  muted: 'bg-ds-hover/70 text-ds-muted group-hover:bg-ds-hover'
} as const

function RowIcon({
  icon: Icon,
  tint
}: {
  icon: typeof Globe2
  tint: keyof typeof ROW_ICON_TINTS
}): ReactElement {
  return (
    <span
      className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-[8px] transition-colors ${ROW_ICON_TINTS[tint]}`}
      aria-hidden
    >
      <Icon className="h-[14px] w-[14px]" strokeWidth={1.9} />
    </span>
  )
}

function SectionHeader({
  label,
  icon,
  collapsed,
  onToggle,
  trailing
}: {
  label: string
  icon: typeof Globe2
  collapsed: boolean
  onToggle: () => void
  trailing?: ReactElement
}): ReactElement {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={!collapsed}
      className={DOCK_SECTION_HEADER_CLASS}
    >
      <RowIcon icon={icon} tint="muted" />
      <span className="ds-operation-dock-section-label min-w-0 flex-1">{label}</span>
      {trailing}
      <ChevronRight
        className={`h-3.5 w-3.5 shrink-0 text-ds-faint transition-transform duration-200 ${
          collapsed ? '' : 'rotate-90'
        }`}
        strokeWidth={2}
        aria-hidden
      />
    </button>
  )
}

export function OperationContextDock({
  workspaceRoot,
  forceCompact = false,
  onExpandRequested,
  onCollapse,
  onOpenChanges,
  onOpenFilesSidebar,
  onEnterIdeMode,
  previewActive,
  previewEnabled,
  onTogglePreview
}: Props): ReactElement | null {
  const { t } = useTranslation('common')
  const {
    blocks,
    activeThreadId,
    threads,
    workspaceDirtyTick
  } = useChatStore(
    useShallow((s) => ({
      blocks: s.blocks,
      activeThreadId: s.activeThreadId,
      threads: s.threads,
      workspaceDirtyTick: s.workspaceDirtyTick
    }))
  )
  const visibleRoot = resolveThreadFilesystemRoot(activeThreadId, threads, workspaceRoot)
  const gitRoot = resolveThreadGitActionRoot(activeThreadId, threads, workspaceRoot)
  const { result: gitResult, loading: gitLoading, reload: reloadGitBranches } = useGitBranches(gitRoot)
  const [branchBase] = useGitBranchCompareBase(
    gitRoot,
    gitResult?.ok ? gitResult.currentBranch : null
  )
  const { result: branchChanges, reload: reloadBranchChanges } = useGitWorkingChanges(
    gitRoot,
    'branch',
    branchBase
  )
  const refreshGitState = useCallback((): void => {
    void reloadGitBranches()
    void reloadBranchChanges()
  }, [reloadBranchChanges, reloadGitBranches])
  useWorkspaceDirtyGitRefresh(workspaceDirtyTick, refreshGitState)
  const todoSnapshot = useMemo(() => extractTodosFromBlocks(blocks), [blocks])
  const todos = useMemo(() => todoSnapshot?.items ?? [], [todoSnapshot])
  const doneCount = todos.filter((item) => item.status === 'completed').length
  const totalCount = todos.length
  const baseTasks = useMemo(() => extractTasksFromBlocks(blocks), [blocks])
  const tasks = useLiveTasks(baseTasks)
  const dockSubagents = useMemo(() => extractSubagentsFromBlocks(blocks), [blocks])
  const changeStats = useMemo(
    () =>
      sumWorkspaceChangeStats(
        collectWorkspaceChangeEntries({
          blocks: [],
          gitFiles: branchChanges?.ok ? branchChanges.files : null
        })
      ),
    [branchChanges]
  )
  const gitDirtyCount = gitResult?.ok ? gitResult.dirtyCount : 0
  const gitReady = gitResult?.ok ?? false
  const gitFilePaths = useMemo(
    () => (branchChanges?.ok ? branchChanges.files.map((file) => file.path) : []),
    [branchChanges]
  )
  const hasGitChanges = gitDirtyCount > 0 || gitFilePaths.length > 0
  const hasChanges = changeStats !== null || hasGitChanges

  const openChangesPanel = (): void => {
    if (!hasChanges) return
    onOpenChanges?.()
  }

  const [collapsed, setCollapsed] = useState({ git: true, process: true })
  const [compact, setCompactMode] = useDockCompact(activeThreadId, visibleRoot)
  /** Which process todo row is expanded to full text (single-line by default). */
  const [expandedTodoKey, setExpandedTodoKey] = useState<string | null>(null)
  const toggle = (key: keyof typeof collapsed): void =>
    setCollapsed((prev) => ({ ...prev, [key]: !prev[key] }))
  const hasTodos = totalCount > 0
  // Follow content availability without overriding manual toggles on progress updates.
  useEffect(() => {
    setCollapsed((prev) => (prev.process === !hasTodos ? prev : { ...prev, process: !hasTodos }))
  }, [hasTodos])
  useEffect(() => {
    setCollapsed((prev) => (prev.git === !hasChanges ? prev : { ...prev, git: !hasChanges }))
  }, [hasChanges])

  if (!visibleRoot) return null

  const workspaceLabel = workspaceLabelFromPath(visibleRoot)

  if (!onCollapse && (forceCompact || compact)) {
    return (
      <div
        className="ds-operation-dock ds-operation-dock--compact ds-no-drag relative z-10"
        data-compact="true"
        data-phase="compact"
      >
        <button
          type="button"
          className="ds-operation-dock-rail__btn ds-operation-dock-rail__btn--toggle"
          onClick={() => { onExpandRequested?.(); setCompactMode(false) }}
          title={t('operationDockExpand')}
          aria-label={t('operationDockExpand')}
          aria-expanded={false}
        >
          <Maximize className="h-4 w-4" strokeWidth={1.75} />
        </button>
        <div className="ds-operation-dock-rail__rule" aria-hidden />
        <div className="ds-operation-dock-rail" role="toolbar" aria-label={t('rightSidebarTabEditor')}>
          <button
            type="button"
            className="ds-operation-dock-rail__btn"
            onClick={onOpenFilesSidebar}
            title={t('rightSidebarTabEditor')}
            aria-label={t('rightSidebarTabEditor')}
          >
            <FolderOpen className="h-[15px] w-[15px]" strokeWidth={1.75} />
          </button>
          <button
            type="button"
            className="ds-operation-dock-rail__btn"
            onClick={onTogglePreview}
            disabled={!previewEnabled}
            aria-pressed={previewActive}
            title={previewEnabled ? t('rightPanelBrowser') : t('terminalWorkspaceRequired')}
            aria-label={t('rightPanelBrowser')}
          >
            <Globe2 className="h-[15px] w-[15px]" strokeWidth={1.75} />
          </button>
          <button
            type="button"
            className="ds-operation-dock-rail__btn"
            onClick={openChangesPanel}
            disabled={!hasChanges}
            title={hasChanges ? t('operationDockOpenChanges') : t('operationDockNoChanges')}
            aria-label={t('operationDockChanges')}
          >
            <FileEdit className="h-[15px] w-[15px]" strokeWidth={1.75} />
          </button>
        </div>
      </div>
    )
  }

  return (
    <div
      className="ds-operation-dock ds-hero-panel ds-glass ds-content-card--interactive ds-no-drag relative z-10 w-full overflow-hidden rounded-[18px]"
      data-compact="false"
      data-phase="expanded"
    >
      <div className="ds-operation-dock-topbar">
        <span className="ds-operation-dock-topbar__title min-w-0 max-w-[66.666%] flex-1 truncate" title={workspaceLabel}>
          {workspaceLabel}
        </span>
        <button
          type="button"
          className="ds-operation-dock-topbar__toggle ml-auto"
          onClick={() => onCollapse ? onCollapse() : setCompactMode(true)}
          title={t('operationDockCollapse')}
          aria-label={t('operationDockCollapse')}
          aria-expanded={true}
        >
          <Minimize className="h-4 w-4" strokeWidth={1.75} />
        </button>
      </div>
      <div className="ds-operation-dock-body">
      <div className="ds-operation-dock-status">
      {onEnterIdeMode ? (
        <div className="ds-operation-dock-status__section">
        <button
          type="button"
          onClick={onEnterIdeMode}
          onPointerEnter={preloadIdeWorkspace}
          onFocus={preloadIdeWorkspace}
          title={t('operationDockEditView')}
          className="ds-operation-dock-repository group"
        >
          <span className="ds-operation-dock-repository__icon" aria-hidden>
            <PanelsTopLeft className="h-[14px] w-[14px]" strokeWidth={1.75} />
          </span>
          <span className="min-w-0 flex-1">
            <span className="ds-operation-dock-repository__name">
              {t('operationDockEditView')}
            </span>
          </span>
        </button>
        </div>
      ) : null}
      <div className="ds-operation-dock-status__section">
      <SectionHeader
        label={t('operationDockGitTitle')}
        icon={GitGraph}
        collapsed={collapsed.git}
        onToggle={() => toggle('git')}
        trailing={
          collapsed.git && hasChanges ? (
            changeStats ? (
              <ChangeDiffStatsLabel stats={changeStats} size="sm" className="shrink-0" />
            ) : (
              <span className="shrink-0 text-[11px] tabular-nums text-ds-faint">
                {t('gitDirtyFiles', { count: gitDirtyCount })}
              </span>
            )
          ) : undefined
        }
      />

      {!collapsed.git ? (
        <div className="ds-operation-dock-status__content mt-1.5 flex flex-col gap-1">
        <button
          type="button"
          onClick={openChangesPanel}
          disabled={!hasChanges}
          title={hasChanges ? t('operationDockOpenChanges') : t('operationDockNoChanges')}
          className={`${DOCK_ROW_CLASS} ${
            hasChanges
              ? 'cursor-pointer text-ds-ink hover:bg-ds-hover/60'
              : 'cursor-default text-ds-faint'
          }`}
        >
          <FileEdit className="h-4 w-4 shrink-0" strokeWidth={1.85} />
          <span className="min-w-0 flex-1 truncate">{t('operationDockChanges')}</span>
          {hasChanges ? (
            changeStats ? (
              <ChangeDiffStatsLabel stats={changeStats} size="md" className="ml-auto shrink-0" />
            ) : (
              <span className="ml-auto shrink-0 text-[12px] tabular-nums text-ds-muted">
                {t('gitDirtyFiles', { count: gitDirtyCount })}
              </span>
            )
          ) : (
            <span className="ml-auto shrink-0 text-[12px] text-ds-faint">{t('operationDockNoChanges')}</span>
          )}
        </button>

        {gitReady ? (
          <div className="ds-operation-dock-branch-picker">
            <GitBranchPicker
              key={gitRoot}
              workspaceRoot={gitRoot}
              compact
              usePortal
              menuPlacement="left"
            />
          </div>
        ) : gitLoading && !gitResult ? (
          <p className="text-[13px] leading-5 text-ds-faint">{t('gitBranchLoading')}</p>
        ) : (
          <p className="text-[13px] leading-5 text-ds-faint">{t('gitNoBranch')}</p>
        )}
      </div>
      ) : null}
      </div>

      {hasTodos ? (
      <div className="ds-operation-dock-status__section">
      <button
        type="button"
        onClick={() => toggle('process')}
        aria-expanded={!collapsed.process}
        className={DOCK_SECTION_HEADER_CLASS}
      >
        <RowIcon icon={ListTodo} tint="muted" />
        <span className="ds-operation-dock-section-label min-w-0 flex-1">
          {t('contextRailProcess')}
        </span>
        {totalCount > 0 ? (
          <span className="flex shrink-0 items-center gap-2">
            <span className="flex items-center gap-[2px]" aria-hidden>
              {todos.map((item) => (
                <span
                  key={item.id}
                  className={`h-3.5 w-[3px] rounded-full ${
                    item.status === 'completed'
                      ? 'bg-emerald-500'
                      : item.status === 'in_progress'
                        ? 'bg-accent'
                        : 'bg-ds-border-muted'
                  }`}
                />
              ))}
            </span>
            <span className="text-[11px] tabular-nums text-ds-faint">
              {doneCount}/{totalCount}
            </span>
          </span>
        ) : null}
        <ChevronRight
          className={`h-3.5 w-3.5 shrink-0 text-ds-faint transition-transform duration-200 ${
            collapsed.process ? '' : 'rotate-90'
          }`}
          strokeWidth={2}
          aria-hidden
        />
      </button>

      {!collapsed.process ? (
        totalCount > 0 ? (
          <ul className="mt-2 flex max-h-[min(36vh,240px)] flex-col gap-0.5 overflow-y-auto overflow-x-hidden rounded-[14px] bg-ds-card/55 p-1.5 dark:bg-white/[0.03]">
            {todos.map((item, index) => {
              const completed = item.status === 'completed'
              const inProgress = item.status === 'in_progress'
              const step = index + 1
              const rowKey = `${item.id}-${item.content}`
              const expanded = expandedTodoKey === rowKey
              return (
                <li key={rowKey}>
                  <button
                    type="button"
                    onClick={() =>
                      setExpandedTodoKey((current) => (current === rowKey ? null : rowKey))
                    }
                    aria-expanded={expanded}
                    title={expanded ? undefined : item.content}
                    className={[
                      'flex w-full items-start gap-2.5 rounded-[10px] px-1.5 py-1.5 text-left transition-colors',
                      'hover:bg-ds-hover/50',
                      inProgress ? 'bg-ds-hover/60' : ''
                    ].join(' ')}
                  >
                    <span
                      className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center"
                      aria-hidden
                    >
                      {completed ? (
                        <span className="flex h-5 w-5 items-center justify-center rounded-full bg-emerald-500 text-white">
                          <Check className="h-3 w-3" strokeWidth={3} />
                        </span>
                      ) : (
                        <span
                          className={[
                            'flex h-5 w-5 items-center justify-center rounded-full text-[11px] font-semibold tabular-nums',
                            inProgress
                              ? 'bg-neutral-900 text-white dark:bg-white dark:text-neutral-900'
                              : 'bg-ds-subtle text-ds-faint'
                          ].join(' ')}
                        >
                          {step}
                        </span>
                      )}
                    </span>
                    <span
                      className={[
                        'min-w-0 flex-1 text-[13px] leading-5',
                        expanded ? 'break-words whitespace-pre-wrap' : 'truncate',
                        completed
                          ? 'text-ds-faint line-through decoration-ds-faint/55'
                          : inProgress
                            ? 'font-semibold text-ds-ink'
                            : 'text-ds-muted'
                      ].join(' ')}
                    >
                      {item.content}
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>
        ) : (
          <p className="mt-1 text-[13px] leading-5 text-ds-faint">{t('contextRailEmptyProcess')}</p>
        )
      ) : null}
      </div>
      ) : null}

      <TaskActivity key={activeThreadId} tasks={tasks} agents={dockSubagents} onOpen={openRunPanel} />
      </div>
      </div>
    </div>
  )
}
