import {
  useCallback,
  useMemo,
  useEffect,
  useRef,
  useState,
  type ReactElement
} from 'react'
import {
  ArrowUpRight,
  Check,
  ChevronDown,
  ChevronRight,
  ChevronsLeftRight,
  GitBranch,
  Github,
  ListChecks,
  ListTodo,
  PanelsTopLeft,
  FileEdit,
  Globe2,
  Loader2,
  Terminal,
  X
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useShallow } from 'zustand/react/shallow'
import { ChangeDiffStatsLabel } from '../ChangeDiffStatsLabel'
import { useGitBranches } from '../../hooks/use-git-branches'
import type { GitRemoteProvider } from '@shared/github-repository'
import gitlabTanukiUrl from '../../assets/brand/gitlab-tanuki.svg'
import { useGitHubRepository } from '../../hooks/use-github-repository'
import { openPreviewUrl } from '../../lib/open-preview-url'
import { useDockSubagents, type DockSubagentView } from '../../hooks/use-dock-subagents'
import { fetchTaskDetail, useLiveTasks } from '../../hooks/use-thread-tasks'
import { useGitWorkingChanges } from '../../hooks/use-git-working-changes'
import { useWorkspaceDirtyGitRefresh } from '../../hooks/use-workspace-dirty-git-refresh'
import {
  collectWorkspaceChangeEntries,
  sumWorkspaceChangeStats
} from '../../lib/workspace-change-stats'
import {
  extractTasksFromBlocks,
  isActiveTaskStatus,
  taskListTitle,
  type TaskItemView
} from '../../lib/extract-tasks-from-blocks'
import {
  isActiveSubagentStatus,
  subagentListTitle
} from '../../lib/extract-subagents-from-blocks'
import { timelineToFlowItems } from '../../lib/task-step-flow'
import { TaskRunDialog } from './TaskRunDialog'
import { StepFlow } from './StepFlow'
import { taskStatusLabelKey } from './task-status'
import { extractTodosFromBlocks } from '../../lib/extract-todos-from-blocks'
import {
  isExplicitGitCommitSelectionNone,
  resolveGitCommitPaths
} from '../../lib/git-commit-selection'
import { resolveThreadFilesystemRoot } from '../../lib/workspace-path'
import { workspaceLabelFromPath } from '../../lib/workspace-label'
import { useChatStore } from '../../store/chat-store'
import { GitBranchPicker } from './GitBranchPicker'
import { GitCommitPopover } from './GitCommitPopover'

type Props = {
  onOpenChanges?: () => void
  /** Enter IDE/editor layout — top entry, labeled as Editor. */
  onEnterIdeMode?: () => void
  previewActive: boolean
  terminalPanelOpen: boolean
  terminalPanelEnabled: boolean
  previewEnabled: boolean
  onTogglePreview: () => void
  onToggleTerminalPanel: () => void
}

const DOCK_ROW_CLASS =
  'group flex w-full items-center gap-2.5 rounded-[10px] px-1.5 py-1.5 text-left text-[13px] font-semibold leading-5 transition'

/** Same horizontal inset / gap as dock rows so icon and label columns line up. */
const DOCK_SECTION_HEADER_CLASS =
  'flex w-full items-center gap-2.5 rounded-[10px] px-1.5 py-1.5 text-left text-ds-muted transition hover:text-ds-ink'

const DOCK_COMPACT_STORAGE_KEY = 'deepseekgui.operationDock.compact'
/** Keep in sync with `.ds-operation-rail` width transition (220ms). */
const DOCK_MOTION_MS = 220

function readStoredDockCompact(): boolean {
  try {
    return window.localStorage.getItem(DOCK_COMPACT_STORAGE_KEY) === 'true'
  } catch {
    return false
  }
}

function persistDockCompact(value: boolean): void {
  try {
    window.localStorage.setItem(DOCK_COMPACT_STORAGE_KEY, String(value))
  } catch {
    /* ignore persistence failures */
  }
}

function prefersReducedMotion(): boolean {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

function RemoteProviderIcon({
  provider,
  className
}: {
  provider: GitRemoteProvider
  className: string
}): ReactElement {
  if (provider === 'gitlab') {
    return (
      <img
        src={gitlabTanukiUrl}
        alt=""
        draggable={false}
        className={`${className} rounded-full bg-white object-cover`}
      />
    )
  }
  if (provider === 'github') return <Github className={className} strokeWidth={1.75} />
  return <GitBranch className={className} strokeWidth={1.75} />
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

function subagentDockDotClass(status: DockSubagentView['status']): string {
  if (status === 'failed') return 'bg-red-500'
  if (status === 'completed') return 'bg-sky-500'
  if (status === 'cancelled') return 'bg-ds-border'
  return 'bg-emerald-500'
}

function SubagentDockRow({ item }: { item: DockSubagentView }): ReactElement {
  const { t } = useTranslation('common')
  const scrollToBlock = useChatStore((s) => s.scrollToBlock)
  const active = isActiveSubagentStatus(item.status)
  const label = subagentListTitle(item, 56, t('contextRailSubagentFallback'))
  const fullPrompt = (item.prompt || '').replace(/\s+/g, ' ').trim()

  return (
    <li
      className={[
        'transition-opacity duration-500',
        item.fading ? 'pointer-events-none opacity-0' : 'opacity-100'
      ].join(' ')}
    >
      <button
        type="button"
        onClick={() => scrollToBlock(item.id)}
        title={fullPrompt || t('contextRailSubagentJump')}
        className="flex w-full items-center gap-2 rounded-[9px] px-1.5 py-1 text-left transition-colors hover:bg-ds-hover/60"
      >
        <span
          className={`h-2 w-2 shrink-0 rounded-full ${subagentDockDotClass(item.status)}`}
          aria-hidden
        />
        <span
          className={[
            'min-w-0 flex-1 truncate text-[12.5px] leading-5 tracking-[-0.01em]',
            active ? 'font-medium text-ds-ink' : 'font-medium text-ds-ink/85'
          ].join(' ')}
        >
          {label}
        </span>
      </button>
    </li>
  )
}

function TaskGroupLabel({ label }: { label: string }): ReactElement {
  return (
    <p className="px-1.5 pb-0.5 pt-1 text-[11px] font-medium tracking-[0.02em] text-ds-faint">
      {label}
    </p>
  )
}

function TaskRow({
  task,
  onDismiss
}: {
  task: TaskItemView
  onDismiss?: () => void
}): ReactElement {
  const { t } = useTranslation()
  const { status } = task
  const running = isActiveTaskStatus(status)
  const [dialogOpen, setDialogOpen] = useState(false)
  // Collapsed by default — expand only when the user wants the step rail.
  const [stepsOpen, setStepsOpen] = useState(false)
  const [timeline, setTimeline] = useState<ReturnType<typeof timelineToFlowItems>>([])
  const [loadingSteps, setLoadingSteps] = useState(false)
  const title = taskListTitle(task)

  useEffect(() => {
    if (!stepsOpen) return
    let cancelled = false
    let interval: number | undefined
    const load = (): void => {
      void fetchTaskDetail(task.id)
        .then((detail) => {
          if (cancelled) return
          if (detail) {
            setTimeline(timelineToFlowItems(detail.timeline))
            if (!isActiveTaskStatus(detail.status) && interval !== undefined) {
              window.clearInterval(interval)
              interval = undefined
            }
          }
          setLoadingSteps(false)
        })
        .catch(() => {
          if (!cancelled) setLoadingSteps(false)
        })
    }
    setLoadingSteps(true)
    load()
    if (running) {
      interval = window.setInterval(load, 1500)
    }
    return () => {
      cancelled = true
      if (interval !== undefined) window.clearInterval(interval)
    }
  }, [stepsOpen, task.id, running])

  return (
    <li className="rounded-[10px] px-0.5 py-0.5">
      <div className="flex items-center gap-1">
        <button
          type="button"
          onClick={() => setStepsOpen((v) => !v)}
          title={task.prompt.trim() || task.id}
          aria-expanded={stepsOpen}
          className="flex min-w-0 flex-1 items-center gap-1.5 rounded-[9px] px-1.5 py-1 text-left transition-colors hover:bg-ds-hover/60"
        >
          <ChevronDown
            className={[
              'h-3.5 w-3.5 shrink-0 text-ds-faint transition-transform duration-200',
              stepsOpen ? 'rotate-0' : '-rotate-90'
            ].join(' ')}
            strokeWidth={1.8}
          />
          <span
            className={[
              'min-w-0 flex-1 truncate text-[12.5px] leading-5 tracking-[-0.01em]',
              running ? 'ds-shiny-text font-medium text-ds-ink' : 'font-medium text-ds-ink/85'
            ].join(' ')}
          >
            {title}
          </span>
          <span className="shrink-0 text-[11px] text-ds-faint">
            {t(taskStatusLabelKey(status))}
          </span>
        </button>
        {!running ? (
          <button
            type="button"
            onClick={() => setDialogOpen(true)}
            className="shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink"
          >
            {t('subagentDetails')}
          </button>
        ) : null}
        {onDismiss ? (
          <button
            type="button"
            onClick={onDismiss}
            title={t('contextRailTaskClear')}
            aria-label={t('contextRailTaskClear')}
            className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-ds-faint transition hover:bg-ds-hover hover:text-ds-ink"
          >
            <X className="h-3.5 w-3.5" strokeWidth={2} />
          </button>
        ) : null}
      </div>

      {stepsOpen ? (
        <div className="mt-1 border-t border-ds-border-muted/40 px-1 pt-1">
          {timeline.length > 0 ? (
            <StepFlow items={timeline} compact />
          ) : loadingSteps ? (
            <div className="flex items-center gap-1.5 px-1 py-1.5 text-[11.5px] text-ds-faint">
              <Loader2 className="h-3 w-3 animate-spin" />
              {t('contextRailTaskLoading')}
            </div>
          ) : (
            <p className="px-1 py-1.5 text-[11.5px] text-ds-faint">
              {running
                ? t('subagentStepFlowWaiting')
                : t('stepFlowEmpty')}
            </p>
          )}
        </div>
      ) : null}

      <TaskRunDialog
        taskId={task.id}
        initialStatus={status}
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
      />
    </li>
  )
}

export function OperationContextDock({
  onOpenChanges,
  onEnterIdeMode,
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
    syncGitCommitSelection,
    workspaceDirtyTick,
    turnDiffByTurnId
  } = useChatStore(
    useShallow((s) => ({
      workspaceRoot: s.workspaceRoot,
      blocks: s.blocks,
      activeThreadId: s.activeThreadId,
      threads: s.threads,
      gitCommitSelectionKey: s.gitCommitSelectionKey,
      gitCommitSelectedPaths: s.gitCommitSelectedPaths,
      syncGitCommitSelection: s.syncGitCommitSelection,
      workspaceDirtyTick: s.workspaceDirtyTick,
      turnDiffByTurnId: s.turnDiffByTurnId
    }))
  )
  const activeThread = activeThreadId
    ? threads.find((thread) => thread.id === activeThreadId)
    : undefined
  const isSessionDraft = activeThread?.envMode === 'worktree'
  const root = resolveThreadFilesystemRoot(activeThreadId, threads, workspaceRoot)
  const { result: gitResult, loading: gitLoading, reload: reloadGitBranches } = useGitBranches(root)
  const { result: gitChanges, loading: gitChangesLoading, reload: reloadGitChanges } = useGitWorkingChanges(root)
  const { result: githubResult, reload: reloadGithubRepository } = useGitHubRepository(root)
  const githubRepo = githubResult?.ok ? githubResult : null
  const refreshGitState = useCallback((): void => {
    void reloadGitBranches()
    void reloadGitChanges()
    void reloadGithubRepository()
  }, [reloadGitBranches, reloadGitChanges, reloadGithubRepository])
  useWorkspaceDirtyGitRefresh(workspaceDirtyTick, refreshGitState)
  const todoSnapshot = useMemo(() => extractTodosFromBlocks(blocks), [blocks])
  const todos = todoSnapshot?.items ?? []
  const doneCount = todos.filter((item) => item.status === 'completed').length
  const totalCount = todos.length
  const baseTasks = useMemo(() => extractTasksFromBlocks(blocks), [blocks])
  const tasks = useLiveTasks(baseTasks)
  /** Local dock dismissals — hide from the rail without cancelling the backend task. */
  const [dismissedTaskIds, setDismissedTaskIds] = useState(() => new Set<string>())
  useEffect(() => {
    setDismissedTaskIds(new Set())
  }, [activeThreadId])
  const visibleTasks = useMemo(
    () => tasks.filter((task) => !dismissedTaskIds.has(task.id)),
    [tasks, dismissedTaskIds]
  )
  const activeTasks = useMemo(
    () => visibleTasks.filter((task) => isActiveTaskStatus(task.status)),
    [visibleTasks]
  )
  const doneTasks = useMemo(
    () => visibleTasks.filter((task) => !isActiveTaskStatus(task.status)),
    [visibleTasks]
  )
  const dismissTask = useCallback((taskId: string): void => {
    setDismissedTaskIds((prev) => {
      if (prev.has(taskId)) return prev
      const next = new Set(prev)
      next.add(taskId)
      return next
    })
  }, [])
  const dockSubagents = useDockSubagents(blocks)
  const changeStats = useMemo(
    () =>
      sumWorkspaceChangeStats(
        collectWorkspaceChangeEntries({
          blocks,
          turnDiffByTurnId,
          gitFiles: isSessionDraft ? [] : gitChanges?.ok ? gitChanges.files : null,
          retainSessionEntriesWhenGitClean: isSessionDraft
        })
      ),
    [blocks, gitChanges, isSessionDraft, turnDiffByTurnId]
  )
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

  const openChangesPanel = (): void => {
    if (!hasChanges) return
    onOpenChanges?.()
  }

  const openGithubRepository = (): void => {
    if (!githubRepo) return
    openPreviewUrl(githubRepo.url)
  }

  const [collapsed, setCollapsed] = useState({ git: true, process: true, tasks: true })
  const [compact, setCompact] = useState(readStoredDockCompact)
  /** Drives rail width via `data-compact` — can lead the DOM swap during motion. */
  const [widthCompact, setWidthCompact] = useState(readStoredDockCompact)
  const [motion, setMotion] = useState<'idle' | 'collapsing' | 'expanding'>('idle')
  const motionTimerRef = useRef<number | null>(null)
  /** Which process todo row is expanded to full text (single-line by default). */
  const [expandedTodoKey, setExpandedTodoKey] = useState<string | null>(null)
  const toggle = (key: keyof typeof collapsed): void =>
    setCollapsed((prev) => ({ ...prev, [key]: !prev[key] }))

  const clearMotionTimer = useCallback((): void => {
    if (motionTimerRef.current != null) {
      window.clearTimeout(motionTimerRef.current)
      motionTimerRef.current = null
    }
  }, [])

  useEffect(() => () => clearMotionTimer(), [clearMotionTimer])

  const setCompactMode = useCallback(
    (value: boolean): void => {
      if (motion !== 'idle') return
      if (value === compact && value === widthCompact) return

      clearMotionTimer()

      if (prefersReducedMotion()) {
        setCompact(value)
        setWidthCompact(value)
        setMotion('idle')
        persistDockCompact(value)
        return
      }

      if (value) {
        // Collapse: shrink rail + fade/squeeze the card, then swap to icon strip.
        setMotion('collapsing')
        setWidthCompact(true)
        motionTimerRef.current = window.setTimeout(() => {
          setCompact(true)
          setMotion('idle')
          persistDockCompact(true)
          motionTimerRef.current = null
        }, DOCK_MOTION_MS)
        return
      }

      // Expand: mount the card while still narrow, then widen + fade in together.
      setCompact(false)
      setMotion('expanding')
      setWidthCompact(true)
      persistDockCompact(false)
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          setWidthCompact(false)
        })
      })
      motionTimerRef.current = window.setTimeout(() => {
        setMotion('idle')
        motionTimerRef.current = null
      }, DOCK_MOTION_MS)
    },
    [clearMotionTimer, compact, motion, widthCompact]
  )

  // Auto-expand a section when it gains content and auto-collapse when it
  // empties. Each effect keys on a single boolean edge so manually toggling
  // one section never overrides another.
  const hasTodos = totalCount > 0
  const hasTasks = visibleTasks.length > 0
  const hasSubagents = dockSubagents.length > 0
  const hasTaskSection = hasTasks || hasSubagents
  useEffect(() => {
    setCollapsed((prev) => (prev.process === !hasTodos ? prev : { ...prev, process: !hasTodos }))
  }, [hasTodos])
  useEffect(() => {
    setCollapsed((prev) =>
      prev.tasks === !hasTaskSection ? prev : { ...prev, tasks: !hasTaskSection }
    )
  }, [hasTaskSection])
  useEffect(() => {
    setCollapsed((prev) => (prev.git === !hasChanges ? prev : { ...prev, git: !hasChanges }))
  }, [hasChanges])

  if (!root) return null

  const workspaceLabel = workspaceLabelFromPath(root)

  // Keep the expanded card mounted while collapsing (fade/squeeze) and while
  // expanding (fade in from the narrow rail). Only idle-compact uses the strip.
  if (compact && motion !== 'expanding') {
    return (
      <div
        className="ds-operation-dock ds-operation-dock--compact ds-no-drag relative z-10"
        data-compact="true"
        data-phase={motion === 'idle' ? 'compact' : motion}
      >
        <button
          type="button"
          className="ds-operation-dock-rail__btn ds-operation-dock-rail__btn--toggle"
          onClick={() => setCompactMode(false)}
          title={t('operationDockExpand')}
          aria-label={t('operationDockExpand')}
          aria-expanded={false}
          disabled={motion !== 'idle'}
        >
          <ChevronsLeftRight className="h-4 w-4" strokeWidth={2.1} />
        </button>
        <div className="ds-operation-dock-rail__rule" aria-hidden />
        <div className="ds-operation-dock-rail" role="toolbar" aria-label={t('rightSidebarTabEditor')}>
          {onEnterIdeMode ? (
            <button
              type="button"
              className="ds-operation-dock-rail__btn"
              onClick={onEnterIdeMode}
              title={t('rightSidebarTabEditor')}
              aria-label={t('rightSidebarTabEditor')}
            >
              <PanelsTopLeft className="h-[15px] w-[15px]" strokeWidth={1.75} />
            </button>
          ) : null}
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
          {githubRepo ? (
            <button
              type="button"
              className="ds-operation-dock-rail__btn"
              onClick={openGithubRepository}
              title={t('operationDockOpenRepository', { repo: githubRepo.nameWithOwner })}
              aria-label={t('operationDockOpenRepository', { repo: githubRepo.nameWithOwner })}
            >
              <RemoteProviderIcon provider={githubRepo.provider} className="h-[15px] w-[15px]" />
            </button>
          ) : null}
          <button
            type="button"
            className="ds-operation-dock-rail__btn"
            onClick={onToggleTerminalPanel}
            disabled={!terminalPanelEnabled}
            aria-pressed={terminalPanelOpen}
            title={terminalPanelEnabled ? t('terminalToggle') : t('terminalWorkspaceRequired')}
            aria-label={t('terminalPanelTitle')}
          >
            <Terminal className="h-[15px] w-[15px]" strokeWidth={1.75} />
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
      data-compact={widthCompact ? 'true' : 'false'}
      data-phase={motion === 'idle' ? 'expanded' : motion}
    >
      <div className="ds-operation-dock-topbar">
        <span className="ds-operation-dock-topbar__title min-w-0 flex-1 truncate" title={workspaceLabel}>
          {workspaceLabel}
        </span>
        <button
          type="button"
          className="ds-operation-dock-topbar__toggle"
          onClick={() => setCompactMode(true)}
          title={t('operationDockCollapse')}
          aria-label={t('operationDockCollapse')}
          aria-expanded={true}
          disabled={motion !== 'idle'}
        >
          <ChevronsLeftRight className="h-4 w-4" strokeWidth={2.1} />
        </button>
      </div>
      <div className="ds-operation-dock-body px-4 py-3.5">
      {onEnterIdeMode ? (
        <>
          <button
            type="button"
            onClick={onEnterIdeMode}
            className={`${DOCK_ROW_CLASS} cursor-pointer text-ds-ink hover:bg-ds-hover/60`}
            title={t('rightSidebarTabEditor')}
            aria-label={t('rightSidebarTabEditor')}
          >
            <RowIcon icon={PanelsTopLeft} tint="violet" />
            <span className="min-w-0 flex-1 truncate">{t('rightSidebarTabEditor')}</span>
          </button>
          <div className="my-2 border-t border-ds-border-muted/40" />
        </>
      ) : null}

      <button
        type="button"
        onClick={onTogglePreview}
        disabled={!previewEnabled}
        className={`${DOCK_ROW_CLASS} ${
          previewEnabled
            ? previewActive
              ? 'bg-accent/[0.09] text-ds-ink'
              : 'cursor-pointer text-ds-ink hover:bg-ds-hover/60'
            : 'cursor-default text-ds-faint opacity-55'
        }`}
        aria-pressed={previewActive}
        title={previewEnabled ? t('rightPanelBrowser') : t('terminalWorkspaceRequired')}
      >
        <RowIcon icon={Globe2} tint="sky" />
        <span className="min-w-0 flex-1 truncate">{t('rightPanelBrowser')}</span>
        {previewActive ? (
          <span className="ml-auto shrink-0 text-[12px] font-medium text-accent">
            {t('operationDockToolOpen')}
          </span>
        ) : null}
      </button>

      <div className="my-2 border-t border-ds-border-muted/40" />

      <button
        type="button"
        onClick={onToggleTerminalPanel}
        disabled={!terminalPanelEnabled}
        className={`${DOCK_ROW_CLASS} ${
          terminalPanelEnabled
            ? terminalPanelOpen
              ? 'bg-accent/[0.09] text-ds-ink'
              : 'cursor-pointer text-ds-ink hover:bg-ds-hover/60'
            : 'cursor-default text-ds-faint opacity-55'
        }`}
        aria-pressed={terminalPanelOpen}
        title={terminalPanelEnabled ? t('terminalToggle') : t('terminalWorkspaceRequired')}
      >
        <RowIcon icon={Terminal} tint="amber" />
        <span className="min-w-0 flex-1 truncate">{t('terminalPanelTitle')}</span>
        {terminalPanelOpen ? (
          <span className="ml-auto shrink-0 text-[12px] font-medium text-accent">
            {t('operationDockToolOpen')}
          </span>
        ) : null}
      </button>

      <div className="my-2 border-t border-ds-border-muted/40" />

      {githubRepo ? (
        <>
          <p className="px-1.5 pb-1 text-[11px] font-medium tracking-[0.01em] text-ds-faint">
            {t('operationDockRepository')}
          </p>
          <button
            type="button"
            onClick={openGithubRepository}
            title={t('operationDockOpenRepository', { repo: githubRepo.nameWithOwner })}
            className={`${DOCK_ROW_CLASS} cursor-pointer text-ds-ink hover:bg-ds-hover/60`}
          >
            <RemoteProviderIcon provider={githubRepo.provider} className="h-4 w-4 shrink-0" />
            <span className="min-w-0 flex-1 truncate">{githubRepo.nameWithOwner}</span>
            <ArrowUpRight className="h-3.5 w-3.5 shrink-0 text-ds-faint" strokeWidth={1.85} />
          </button>
          <div className="my-2 border-t border-ds-border-muted/40" />
        </>
      ) : null}

      <SectionHeader
        label={t('operationDockGitTitle')}
        icon={GitBranch}
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
        <div className="mt-1.5 flex flex-col gap-1">
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
                    {expanded ? (
                      <ChevronDown
                        className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ds-faint/70"
                        strokeWidth={2}
                        aria-hidden
                      />
                    ) : (
                      <ChevronRight
                        className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ds-faint/70"
                        strokeWidth={2}
                        aria-hidden
                      />
                    )}
                  </button>
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
        icon={ListChecks}
        collapsed={collapsed.tasks}
        onToggle={() => toggle('tasks')}
        trailing={
          hasTaskSection ? (
            <span className="shrink-0 text-[11px] tabular-nums text-ds-faint">
              {visibleTasks.length + dockSubagents.length}
            </span>
          ) : undefined
        }
      />

      {!collapsed.tasks ? (
        hasTaskSection ? (
          <div className="mt-1.5 max-h-[min(36vh,240px)] space-y-0.5 overflow-y-auto overflow-x-hidden">
            {hasTasks ? (
              <>
                {hasSubagents ? <TaskGroupLabel label={t('contextRailTaskGroup')} /> : null}
                <ul className="space-y-0.5">
                  {[...activeTasks, ...doneTasks].map((task) => (
                    <TaskRow
                      key={task.id}
                      task={task}
                      onDismiss={
                        isActiveTaskStatus(task.status) ? undefined : () => dismissTask(task.id)
                      }
                    />
                  ))}
                </ul>
              </>
            ) : null}
            {hasSubagents ? (
              <>
                <TaskGroupLabel label={t('contextRailSubagentGroup')} />
                <ul className="space-y-0.5">
                  {dockSubagents.map((item) => (
                    <SubagentDockRow key={item.id} item={item} />
                  ))}
                </ul>
              </>
            ) : null}
          </div>
        ) : (
          <p className="mt-1 text-[13px] leading-5 text-ds-faint">{t('contextRailEmptyTasks')}</p>
        )
      ) : null}
      </div>
    </div>
  )
}
