import { useCallback, useMemo, useEffect, useState, type ReactElement } from 'react'
import {
  CheckCircle2,
  ChevronRight,
  Circle,
  Code2,
  FileEdit,
  Globe2,
  Terminal
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useShallow } from 'zustand/react/shallow'
import type { ChatBlock } from '../../agent/types'
import { ChangeDiffStatsLabel } from '../ChangeDiffStatsLabel'
import { useGitBranches } from '../../hooks/use-git-branches'
import { useLiveTasks } from '../../hooks/use-thread-tasks'
import { useGitWorkingChanges } from '../../hooks/use-git-working-changes'
import { sumDiffStats } from '../../lib/diff-stats'
import {
  extractTasksFromBlocks,
  isActiveTaskStatus,
  type TaskItemView
} from '../../lib/extract-tasks-from-blocks'
import { TaskRunDialog } from './TaskRunDialog'
import { TaskStatusGlyph, taskStatusLabelKey } from './task-status'
import { extractTodosFromBlocks } from '../../lib/extract-todos-from-blocks'
import {
  isExplicitGitCommitSelectionNone,
  resolveGitCommitPaths
} from '../../lib/git-commit-selection'
import { resolveActiveThreadWorkspace } from '../../lib/workspace-path'
import { useChatStore } from '../../store/chat-store'
import { GitBranchPicker } from './GitBranchPicker'
import { GitCommitPopover } from './GitCommitPopover'

type Props = {
  onOpenChanges?: () => void
  onOpenEditor?: () => void
  previewActive: boolean
  terminalPanelOpen: boolean
  terminalPanelEnabled: boolean
  previewEnabled: boolean
  onTogglePreview: () => void
  onToggleTerminalPanel: () => void
}

function sessionChangePatches(blocks: ChatBlock[]): Array<string | undefined> {
  return blocks.flatMap((block) =>
    block.kind === 'tool' && block.toolKind === 'file_change' ? [block.detail] : []
  )
}

const DOCK_ROW_CLASS =
  'group flex w-full items-center gap-2.5 rounded-[10px] px-1.5 py-1.5 text-left text-[13px] leading-5 transition'

const ROW_ICON_TINTS = {
  violet: 'bg-violet-500/10 text-violet-500 group-hover:bg-violet-500/16 dark:text-violet-300',
  sky: 'bg-sky-500/10 text-sky-500 group-hover:bg-sky-500/16 dark:text-sky-300',
  amber: 'bg-amber-500/12 text-amber-600 group-hover:bg-amber-500/18 dark:text-amber-300'
} as const

function RowIcon({
  icon: Icon,
  tint
}: {
  icon: typeof Code2
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
  collapsed,
  onToggle,
  trailing
}: {
  label: string
  collapsed: boolean
  onToggle: () => void
  trailing?: ReactElement
}): ReactElement {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={!collapsed}
      className="flex w-full items-center gap-1.5 rounded-md py-0.5 text-left text-ds-faint transition hover:text-ds-muted"
    >
      <span className="ds-operation-dock-section-label flex-1">{label}</span>
      {trailing}
      <ChevronRight
        className={`h-3.5 w-3.5 shrink-0 transition-transform duration-200 ${collapsed ? '' : 'rotate-90'}`}
        strokeWidth={2}
        aria-hidden
      />
    </button>
  )
}

function TaskRow({ task }: { task: TaskItemView }): ReactElement {
  const { t } = useTranslation()
  const { status } = task
  const running = status === 'running'
  const [open, setOpen] = useState(false)

  return (
    <li>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="flex w-full items-center gap-2 rounded-[9px] px-1.5 py-1 text-left transition-colors hover:bg-ds-hover/60"
      >
        <TaskStatusGlyph status={status} />
        <span
          className={[
            'min-w-0 flex-1 truncate font-mono text-[12px] leading-5',
            running ? 'ds-shiny-text font-medium text-ds-ink' : 'text-ds-muted'
          ].join(' ')}
        >
          {task.id}
        </span>
        <span className="shrink-0 text-[11px] text-ds-faint">{t(taskStatusLabelKey(status))}</span>
      </button>
      <TaskRunDialog
        taskId={task.id}
        initialStatus={status}
        open={open}
        onClose={() => setOpen(false)}
      />
    </li>
  )
}

export function OperationContextDock({
  onOpenChanges,
  onOpenEditor,
  previewActive,
  terminalPanelOpen,
  terminalPanelEnabled,
  previewEnabled,
  onTogglePreview,
  onToggleTerminalPanel
}: Props): ReactElement | null {
  const { t } = useTranslation('common')
  const {
    workspaceRoot,
    blocks,
    activeThreadId,
    threads,
    gitCommitSelectionKey,
    gitCommitSelectedPaths,
    syncGitCommitSelection
  } = useChatStore(
    useShallow((s) => ({
      workspaceRoot: s.workspaceRoot,
      blocks: s.blocks,
      activeThreadId: s.activeThreadId,
      threads: s.threads,
      gitCommitSelectionKey: s.gitCommitSelectionKey,
      gitCommitSelectedPaths: s.gitCommitSelectedPaths,
      syncGitCommitSelection: s.syncGitCommitSelection
    }))
  )
  const root = resolveActiveThreadWorkspace(activeThreadId, threads, workspaceRoot)
  const { result: gitResult, loading: gitLoading, reload: reloadGitBranches } = useGitBranches(root)
  const { result: gitChanges, loading: gitChangesLoading, reload: reloadGitChanges } = useGitWorkingChanges(root)
  const todoSnapshot = useMemo(() => extractTodosFromBlocks(blocks), [blocks])
  const todos = todoSnapshot?.items ?? []
  const doneCount = todos.filter((item) => item.status === 'completed').length
  const totalCount = todos.length
  const baseTasks = useMemo(() => extractTasksFromBlocks(blocks), [blocks])
  const tasks = useLiveTasks(baseTasks)
  const activeTasks = useMemo(() => tasks.filter((task) => isActiveTaskStatus(task.status)), [tasks])
  const doneTasks = useMemo(() => tasks.filter((task) => !isActiveTaskStatus(task.status)), [tasks])
  const changeStats = useMemo(() => {
    const gitPatches = gitChanges?.ok ? gitChanges.files.map((file) => file.patch) : []
    return sumDiffStats([...sessionChangePatches(blocks), ...gitPatches])
  }, [blocks, gitChanges])
  const gitDirtyCount = gitResult?.ok ? gitResult.dirtyCount : 0
  const gitReady = gitResult?.ok ?? false
  const gitFilePaths = useMemo(
    () => (gitChanges?.ok ? gitChanges.files.map((file) => file.path) : []),
    [gitChanges]
  )
  useEffect(() => {
    if (gitChanges == null || !gitChanges.ok) return
    syncGitCommitSelection(gitFilePaths)
  }, [gitChanges, gitFilePaths, syncGitCommitSelection])
  const commitFilePaths = useMemo(
    () =>
      resolveGitCommitPaths(gitCommitSelectedPaths, gitFilePaths, gitCommitSelectionKey, root),
    [gitCommitSelectedPaths, gitFilePaths, gitCommitSelectionKey, root]
  )
  const explicitSelectNone = isExplicitGitCommitSelectionNone(
    gitCommitSelectionKey,
    gitCommitSelectedPaths,
    gitFilePaths,
    root
  )
  const canCommit = gitReady && gitDirtyCount > 0 && !explicitSelectNone
  const hasGitChanges = gitDirtyCount > 0 || gitFilePaths.length > 0
  const hasChanges = changeStats !== null || hasGitChanges

  const refreshGitState = useCallback((): void => {
    void reloadGitBranches()
    void reloadGitChanges()
  }, [reloadGitBranches, reloadGitChanges])

  const openChangesPanel = (): void => {
    if (!hasChanges) return
    onOpenChanges?.()
  }

  const [collapsed, setCollapsed] = useState({ tools: false, git: true, process: true, tasks: true })
  const toggle = (key: keyof typeof collapsed): void =>
    setCollapsed((prev) => ({ ...prev, [key]: !prev[key] }))

  // Auto-expand a section when it gains content and auto-collapse when it
  // empties. Each effect keys on a single boolean edge so manually toggling
  // one section never overrides another. The "tools" section has no effect:
  // it stays expanded by default.
  const hasTodos = totalCount > 0
  const hasTasks = tasks.length > 0
  useEffect(() => {
    setCollapsed((prev) => (prev.process === !hasTodos ? prev : { ...prev, process: !hasTodos }))
  }, [hasTodos])
  useEffect(() => {
    setCollapsed((prev) => (prev.tasks === !hasTasks ? prev : { ...prev, tasks: !hasTasks }))
  }, [hasTasks])
  useEffect(() => {
    setCollapsed((prev) => (prev.git === !hasChanges ? prev : { ...prev, git: !hasChanges }))
  }, [hasChanges])

  if (!root) return null

  return (
    <div className="ds-operation-dock ds-hero-panel ds-glass ds-content-card--interactive ds-no-drag relative z-10 w-full overflow-hidden rounded-[22px] px-4 py-3.5">
      <SectionHeader
        label={t('operationDockToolsTitle')}
        collapsed={collapsed.tools}
        onToggle={() => toggle('tools')}
      />

      {!collapsed.tools ? (
        <div className="mt-1.5 flex flex-col gap-1">
        <button
          type="button"
          onClick={() => onOpenEditor?.()}
          className={`${DOCK_ROW_CLASS} cursor-pointer text-ds-muted hover:bg-ds-hover/60 hover:text-ds-ink`}
        >
          <RowIcon icon={Code2} tint="violet" />
          <span className="min-w-0 flex-1 truncate">{t('rightSidebarTabEditor')}</span>
        </button>

        <button
          type="button"
          onClick={onTogglePreview}
          disabled={!previewEnabled}
          className={`${DOCK_ROW_CLASS} ${
            previewEnabled
              ? previewActive
                ? 'bg-accent/[0.09] text-ds-ink'
                : 'cursor-pointer text-ds-muted hover:bg-ds-hover/60 hover:text-ds-ink'
              : 'cursor-default text-ds-faint opacity-55'
          }`}
          aria-pressed={previewActive}
          title={previewEnabled ? t('rightPanelBrowser') : t('terminalWorkspaceRequired')}
        >
          <RowIcon icon={Globe2} tint="sky" />
          <span className="min-w-0 flex-1 truncate">{t('rightPanelBrowser')}</span>
          {previewActive ? (
            <span className="ml-auto shrink-0 text-[12px] font-medium text-accent">{t('operationDockToolOpen')}</span>
          ) : null}
        </button>

        <button
          type="button"
          onClick={onToggleTerminalPanel}
          disabled={!terminalPanelEnabled}
          className={`${DOCK_ROW_CLASS} ${
            terminalPanelEnabled
              ? terminalPanelOpen
                ? 'bg-accent/[0.09] text-ds-ink'
                : 'cursor-pointer text-ds-muted hover:bg-ds-hover/60 hover:text-ds-ink'
              : 'cursor-default text-ds-faint opacity-55'
          }`}
          aria-pressed={terminalPanelOpen}
          title={terminalPanelEnabled ? t('terminalToggle') : t('terminalWorkspaceRequired')}
        >
          <RowIcon icon={Terminal} tint="amber" />
          <span className="min-w-0 flex-1 truncate">{t('terminalPanelTitle')}</span>
          {terminalPanelOpen ? (
            <span className="ml-auto shrink-0 text-[12px] font-medium text-accent">{t('operationDockToolOpen')}</span>
          ) : null}
        </button>
      </div>
      ) : null}

      <div className="my-2 border-t border-ds-border-muted/40" />

      <SectionHeader
        label={t('operationDockGitTitle')}
        collapsed={collapsed.git}
        onToggle={() => toggle('git')}
      />

      {!collapsed.git ? (
        <div className="mt-1.5 flex flex-col gap-1">
        <button
          type="button"
          onClick={openChangesPanel}
          disabled={!hasChanges}
          title={hasChanges ? t('operationDockOpenChanges') : t('operationDockNoChanges')}
          className={`${DOCK_ROW_CLASS} ${
            hasChanges
              ? 'cursor-pointer text-ds-muted hover:bg-ds-hover/60 hover:text-ds-ink'
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
          <>
            <GitBranchPicker
              key={root}
              workspaceRoot={root}
              compact
              usePortal
              menuPlacement="below"
            />
            <GitCommitPopover
              workspaceRoot={root}
              currentBranch={gitResult?.ok ? gitResult.currentBranch : null}
              gitFiles={gitChanges?.ok ? gitChanges.files : []}
              gitFilesLoading={gitChangesLoading}
              gitDirtyCount={gitDirtyCount}
              enabled={canCommit}
              rowClassName={DOCK_ROW_CLASS}
              onOpenChanges={hasChanges ? openChangesPanel : undefined}
              onRefreshGit={refreshGitState}
              onCommitted={refreshGitState}
            />
            {hasChanges && !hasGitChanges ? (
              <p className="px-1 text-[12px] leading-5 text-ds-faint">
                {t('operationDockCommitSessionOnly')}
              </p>
            ) : null}
          </>
        ) : gitLoading && !gitResult ? (
          <p className="text-[13px] leading-5 text-ds-faint">{t('gitBranchLoading')}</p>
        ) : (
          <p className="text-[13px] leading-5 text-ds-faint">{t('gitNoBranch')}</p>
        )}
      </div>
      ) : null}

      <div className="my-2 border-t border-ds-border-muted/40" />

      <SectionHeader
        label={t('contextRailProcess')}
        collapsed={collapsed.process}
        onToggle={() => toggle('process')}
        trailing={
          totalCount > 0 ? (
            <span className="shrink-0 text-[11px] tabular-nums text-ds-faint">
              {doneCount}/{totalCount}
            </span>
          ) : undefined
        }
      />

      {!collapsed.process ? (
        totalCount > 0 ? (
          <ul className="mt-1.5 max-h-[min(36vh,240px)] space-y-0.5 overflow-y-auto overflow-x-hidden">
            {todos.map((item) => {
              const completed = item.status === 'completed'
              const inProgress = item.status === 'in_progress'
              return (
                <li
                  key={`${item.id}-${item.content}`}
                  className={[
                    'flex items-start gap-2.5 rounded-[9px] px-1.5 py-1 transition-colors',
                    inProgress ? 'bg-accent/[0.07]' : ''
                  ].join(' ')}
                >
                  <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center" aria-hidden>
                    {completed ? (
                      <CheckCircle2
                        className="h-4 w-4 text-emerald-600/85 dark:text-emerald-400/85"
                        strokeWidth={1.9}
                      />
                    ) : inProgress ? (
                      <span className="relative flex h-3.5 w-3.5 items-center justify-center">
                        <span className="absolute inline-flex h-3.5 w-3.5 animate-ping rounded-full bg-accent/30" />
                        <span className="relative inline-flex h-[7px] w-[7px] rounded-full bg-accent" />
                      </span>
                    ) : (
                      <Circle className="h-4 w-4 text-ds-faint/80" strokeWidth={1.85} />
                    )}
                  </span>
                  <span
                    className={[
                      'min-w-0 break-words text-[13px] leading-5',
                      completed
                        ? 'text-ds-faint line-through decoration-ds-faint/55'
                        : inProgress
                          ? 'ds-shiny-text font-medium text-ds-ink'
                          : 'text-ds-muted'
                    ].join(' ')}
                  >
                    {item.content}
                  </span>
                </li>
              )
            })}
          </ul>
        ) : (
          <p className="mt-1 text-[13px] leading-5 text-ds-faint">{t('contextRailEmptyProcess')}</p>
        )
      ) : null}

      <div className="my-2 border-t border-ds-border-muted/40" />

      <SectionHeader
        label={t('contextRailTasks')}
        collapsed={collapsed.tasks}
        onToggle={() => toggle('tasks')}
        trailing={
          tasks.length > 0 ? (
            <span className="shrink-0 text-[11px] tabular-nums text-ds-faint">{tasks.length}</span>
          ) : undefined
        }
      />

      {!collapsed.tasks ? (
        tasks.length > 0 ? (
          <ul className="mt-1.5 max-h-[min(36vh,240px)] space-y-0.5 overflow-y-auto overflow-x-hidden">
            {[...activeTasks, ...doneTasks].map((task) => (
              <TaskRow key={task.id} task={task} />
            ))}
          </ul>
        ) : (
          <p className="mt-1 text-[13px] leading-5 text-ds-faint">{t('contextRailEmptyTasks')}</p>
        )
      ) : null}
    </div>
  )
}
