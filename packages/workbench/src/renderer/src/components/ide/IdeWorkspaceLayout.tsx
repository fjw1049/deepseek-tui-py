import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type ReactElement,
  type ReactNode
} from 'react'
import {
  FileEdit,
  Folders,
  MessageSquare,
  PanelRight,
  PanelRightClose,
  Search
} from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { ChatBlock } from '../../agent/types'
import {
  clampIdeChatRailWidth,
  IDE_CHAT_RAIL_DEFAULT_WIDTH,
  IDE_CHAT_RAIL_MAX_WIDTH,
  IDE_CHAT_RAIL_MIN_WIDTH,
  nextIdeActivitySelection,
  persistIdeActivitySidebarVisible,
  persistIdeCenterTab,
  persistIdeChatRailWidth,
  readStoredIdeActivitySidebarVisible,
  readStoredIdeCenterTab,
  readStoredIdeChatRailWidth,
  type IdeCenterTab
} from '../../lib/workbench-layout-mode'
import { workspaceLabelFromPath } from '../../lib/workspace-label'
import { IDE_QUICK_OPEN_EVENT } from '../../lib/workspace-editor-events'
import { useWorkspaceEditorStore } from '../../store/workspace-editor-store'
import { useGitWorkingChanges } from '../../hooks/use-git-working-changes'
import { useWorkspaceDirtyGitRefresh } from '../../hooks/use-workspace-dirty-git-refresh'
import { collectWorkspaceChangeEntries } from '../../lib/workspace-change-stats'
import type { ChangeReviewContext } from '../../lib/change-review'
import { useChatStore } from '../../store/chat-store'
import { IdeProjectPicker, type IdeProjectOption } from './IdeProjectPicker'
import { IdeQuickOpenPalette } from './IdeQuickOpenPalette'

const WorkspaceEditorPanel = lazy(() =>
  import('../workspace-editor/WorkspaceEditorPanel').then((module) => ({
    default: module.WorkspaceEditorPanel
  }))
)
const ChangeInspector = lazy(() =>
  import('../ChangeInspector').then((module) => ({ default: module.ChangeInspector }))
)

type Props = {
  workspaceRoot: string
  blocks: ChatBlock[]
  /** Display name for the active project (basename); path is shown separately. */
  projectLabel?: string | null
  projectOptions?: ReadonlyArray<IdeProjectOption>
  onSelectProject?: (workspacePath: string) => void
  onBrowseProject?: () => void
  chatRail: ReactNode
  onExitIdeMode: () => void
  onOpenFileInEditor: (path: string, line?: number) => void
  changesContext?: ChangeReviewContext
  changesTurnId?: string | null
  changesProjectRoot?: string | null
  onChangesContextChange?: (context: ChangeReviewContext) => void
  /** Imperative center-tab request from parent (e.g. open diff from composer). */
  requestedCenterTab?: IdeCenterTab | null
  onRequestedCenterTabConsumed?: () => void
  /** Terminal eats the editor column; the chat rail grows to fill. */
  terminalMaximized?: boolean
}

const CHANGES_LIST_WIDTH_KEY = 'deepseekgui.layout.ideChangesListWidth'
const CHANGES_LIST_DEFAULT = 240
const CHANGES_LIST_MIN = 180
const CHANGES_LIST_MAX = 420

function clampChangesListWidth(width: number): number {
  return Math.min(CHANGES_LIST_MAX, Math.max(CHANGES_LIST_MIN, Math.round(width)))
}

function readStoredChangesListWidth(): number {
  try {
    const raw = window.localStorage.getItem(CHANGES_LIST_WIDTH_KEY)
    if (!raw) return CHANGES_LIST_DEFAULT
    const parsed = Number(raw)
    if (!Number.isFinite(parsed)) return CHANGES_LIST_DEFAULT
    return clampChangesListWidth(parsed)
  } catch {
    return CHANGES_LIST_DEFAULT
  }
}

function persistChangesListWidth(width: number): void {
  try {
    window.localStorage.setItem(CHANGES_LIST_WIDTH_KEY, String(clampChangesListWidth(width)))
  } catch {
    /* ignore */
  }
}

function PanelFallback(): ReactElement {
  return <div className="h-full w-full bg-ds-canvas" />
}

function ActivityButton({
  active,
  label,
  badge,
  children,
  onClick
}: {
  active: boolean
  label: string
  badge?: number
  children: ReactNode
  onClick: () => void
}): ReactElement {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      aria-pressed={active}
      onClick={onClick}
      className={`relative inline-flex h-9 w-9 items-center justify-center rounded-md transition ${
        active
          ? 'bg-ds-hover text-ds-ink'
          : 'text-ds-faint hover:bg-ds-hover/55 hover:text-ds-muted'
      }`}
    >
      {children}
      {badge && badge > 0 ? (
        <span className="absolute right-0.5 top-0.5 min-w-[14px] rounded-full bg-ds-ink px-1 text-[9px] font-semibold leading-[14px] text-ds-canvas">
          {badge > 99 ? '99+' : badge}
        </span>
      ) : null}
    </button>
  )
}

export function IdeWorkspaceLayout({
  workspaceRoot,
  blocks,
  projectLabel = null,
  projectOptions = [],
  onSelectProject,
  onBrowseProject,
  chatRail,
  onExitIdeMode,
  onOpenFileInEditor,
  changesContext = 'working-tree',
  changesTurnId = null,
  changesProjectRoot = null,
  onChangesContextChange,
  requestedCenterTab = null,
  onRequestedCenterTabConsumed,
  terminalMaximized = false
}: Props): ReactElement {
  const { t } = useTranslation('common')
  const openEditorFile = useWorkspaceEditorStore((s) => s.openFile)

  const [centerTab, setCenterTab] = useState<IdeCenterTab>(readStoredIdeCenterTab)
  /** VS Code-style: click the active activity icon again to collapse the side panel. */
  const [activitySidebarVisible, setActivitySidebarVisible] = useState(
    readStoredIdeActivitySidebarVisible
  )
  const [quickOpenOpen, setQuickOpenOpen] = useState(false)
  const [chatRailVisible, setChatRailVisible] = useState(true)
  const [chatRailWidth, setChatRailWidth] = useState(readStoredIdeChatRailWidth)
  const [changesListWidth, setChangesListWidth] = useState(readStoredChangesListWidth)
  const [changesFocusPath, setChangesFocusPath] = useState<string | null>(null)
  const resizeStateRef = useRef<{
    pointerId: number
    startX: number
    startWidth: number
    pendingWidth: number
  } | null>(null)
  const changesListResizeRef = useRef<{
    pointerId: number
    startX: number
    startWidth: number
    pendingWidth: number
  } | null>(null)
  const workspaceDirtyTick = useChatStore((s) => s.workspaceDirtyTick)
  const { result: gitChanges, reload: reloadGitChanges } = useGitWorkingChanges(workspaceRoot)
  useWorkspaceDirtyGitRefresh(workspaceDirtyTick, reloadGitChanges)
  const changeBadge = collectWorkspaceChangeEntries({
    blocks,
    gitFiles: gitChanges?.ok ? gitChanges.files : null
  }).length

  useEffect(() => {
    persistIdeCenterTab(centerTab === 'search' ? 'files' : centerTab)
  }, [centerTab])

  useEffect(() => {
    persistIdeActivitySidebarVisible(activitySidebarVisible)
  }, [activitySidebarVisible])

  useEffect(() => {
    if (!requestedCenterTab) return
    if (requestedCenterTab === 'search') {
      setQuickOpenOpen(true)
      onRequestedCenterTabConsumed?.()
      return
    }
    setCenterTab(requestedCenterTab)
    setActivitySidebarVisible(true)
    onRequestedCenterTabConsumed?.()
  }, [onRequestedCenterTabConsumed, requestedCenterTab])

  useEffect(() => {
    const onOpenChanges = (event: Event): void => {
      const path = (event as CustomEvent<{ path?: string }>).detail?.path
      if (typeof path === 'string' && path.trim()) setChangesFocusPath(path.trim())
    }
    const onQuickOpen = (): void => setQuickOpenOpen((open) => !open)
    window.addEventListener('deepseekgui:open-changes-panel', onOpenChanges)
    window.addEventListener(IDE_QUICK_OPEN_EVENT, onQuickOpen)
    return () => {
      window.removeEventListener('deepseekgui:open-changes-panel', onOpenChanges)
      window.removeEventListener(IDE_QUICK_OPEN_EVENT, onQuickOpen)
    }
  }, [])

  const selectActivity = useCallback(
    (item: IdeCenterTab) => {
      if (item === 'changes' && centerTab !== 'changes') {
        onChangesContextChange?.('working-tree')
      }
      const next = nextIdeActivitySelection(centerTab, activitySidebarVisible, item)
      setCenterTab(next.tab)
      setActivitySidebarVisible(next.sidebarVisible)
    },
    [activitySidebarVisible, centerTab, onChangesContextChange]
  )

  const handleQuickOpenFile = useCallback(
    (path: string) => {
      setQuickOpenOpen(false)
      setCenterTab('files')
      setActivitySidebarVisible(true)
      void openEditorFile(path, workspaceRoot)
    },
    [openEditorFile, workspaceRoot]
  )

  const handleRevealChangeFile = useCallback(
    (path: string, line?: number) => {
      onOpenFileInEditor(path, line)
    },
    [onOpenFileInEditor]
  )

  const beginChangesListResize = (event: ReactPointerEvent<HTMLDivElement>): void => {
    if (event.button !== 0) return
    event.preventDefault()
    event.stopPropagation()
    changesListResizeRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startWidth: changesListWidth,
      pendingWidth: changesListWidth
    }
    const onMove = (moveEvent: PointerEvent): void => {
      const state = changesListResizeRef.current
      if (!state || moveEvent.pointerId !== state.pointerId) return
      const next = clampChangesListWidth(state.startWidth + moveEvent.clientX - state.startX)
      state.pendingWidth = next
      setChangesListWidth(next)
    }
    const onEnd = (endEvent: PointerEvent): void => {
      const state = changesListResizeRef.current
      if (!state || endEvent.pointerId !== state.pointerId) return
      persistChangesListWidth(state.pendingWidth)
      changesListResizeRef.current = null
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onEnd)
      window.removeEventListener('pointercancel', onEnd)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onEnd)
    window.addEventListener('pointercancel', onEnd)
  }

  const beginChatRailResize = (event: ReactPointerEvent<HTMLDivElement>): void => {
    if (event.button !== 0) return
    event.preventDefault()
    event.stopPropagation()
    resizeStateRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startWidth: chatRailWidth,
      pendingWidth: chatRailWidth
    }
    const onMove = (moveEvent: PointerEvent): void => {
      const state = resizeStateRef.current
      if (!state || moveEvent.pointerId !== state.pointerId) return
      const next = clampIdeChatRailWidth(state.startWidth + state.startX - moveEvent.clientX)
      state.pendingWidth = next
      setChatRailWidth(next)
    }
    const onEnd = (endEvent: PointerEvent): void => {
      const state = resizeStateRef.current
      if (!state || endEvent.pointerId !== state.pointerId) return
      persistIdeChatRailWidth(state.pendingWidth)
      resizeStateRef.current = null
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onEnd)
      window.removeEventListener('pointercancel', onEnd)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onEnd)
    window.addEventListener('pointercancel', onEnd)
  }

  const showChangesList = centerTab === 'changes' && activitySidebarVisible
  const showChangesDiff = centerTab === 'changes'
  const editorHideTree = !activitySidebarVisible || centerTab === 'changes'

  const projectName =
    projectLabel?.trim() ||
    workspaceLabelFromPath(workspaceRoot) ||
    t('ideWorkspaceTitle')
  const projectPath = workspaceRoot.trim()
  const showProjectPicker = Boolean(onSelectProject)

  return (
    <div className="ds-ide-workspace relative flex h-full min-h-0 min-w-0 flex-1 flex-col bg-ds-canvas text-ds-ink">
      <header className="ds-workbench-topbar ds-surface-divider relative z-10 shrink-0">
        <div className="ds-ide-topbar__inner">
          <div className="ds-ide-topbar__leading min-w-0">
            {showProjectPicker ? (
              <IdeProjectPicker
                currentPath={projectPath}
                projectName={projectName}
                options={projectOptions}
                onSelectProject={onSelectProject!}
                {...(onBrowseProject ? { onBrowseProject } : {})}
              />
            ) : (
              <div className="ds-ide-project-picker__identity min-w-0">
                <span className="ds-ide-project-picker__name truncate">{projectName}</span>
                <span className="ds-ide-project-picker__path truncate">
                  {projectPath || t('ideWorkspaceNoRoot')}
                </span>
              </div>
            )}
          </div>
          {/* Trailing chrome actions — transparent (no canvas/white chip fill). */}
          <div className="ds-ide-topbar__actions ds-no-drag">
            <button
              type="button"
              className="ds-ide-topbar__action ds-ide-topbar__action--labeled"
              title={t('ideSwitchToChat')}
              onClick={onExitIdeMode}
            >
              <MessageSquare className="h-3.5 w-3.5" strokeWidth={1.85} />
              <span>{t('ideModeChat')}</span>
            </button>
            <button
              type="button"
              className="ds-ide-topbar__action"
              aria-pressed={chatRailVisible}
              title={chatRailVisible ? t('ideChatRailHide') : t('ideChatRailShow')}
              onClick={() => setChatRailVisible((current) => !current)}
            >
              {chatRailVisible ? (
                <PanelRightClose className="h-3.5 w-3.5" strokeWidth={1.85} />
              ) : (
                <PanelRight className="h-3.5 w-3.5" strokeWidth={1.85} />
              )}
              <span className="sr-only">
                {chatRailVisible ? t('ideChatRailHide') : t('ideChatRailShow')}
              </span>
            </button>
          </div>
        </div>
      </header>

      <div className="flex min-h-0 min-w-0 flex-1 overflow-hidden">
        <nav
          className="ds-ide-activity-bar flex w-11 shrink-0 flex-col items-center gap-1 bg-ds-canvas py-2"
          aria-label={t('ideActivityBarLabel')}
        >
          <ActivityButton
            active={centerTab === 'files' && activitySidebarVisible}
            label={t('ideActivityFiles')}
            onClick={() => selectActivity('files')}
          >
            <Folders className="h-4 w-4" strokeWidth={1.85} />
          </ActivityButton>
          <ActivityButton
            active={centerTab === 'changes' && activitySidebarVisible}
            label={t('ideActivityChanges')}
            badge={changeBadge}
            onClick={() => selectActivity('changes')}
          >
            <FileEdit className="h-4 w-4" strokeWidth={1.85} />
          </ActivityButton>
          <ActivityButton
            active={quickOpenOpen}
            label={t('ideActivitySearch')}
            onClick={() => setQuickOpenOpen((open) => !open)}
          >
            <Search className="h-4 w-4" strokeWidth={1.85} />
          </ActivityButton>
        </nav>

          <div className="flex min-h-0 min-w-0 flex-1 overflow-hidden">
            {terminalMaximized ? null : showChangesList ? (
              <div
                className="ds-ide-changes-list relative flex h-full min-h-0 shrink-0 flex-col"
                style={{ width: changesListWidth }}
              >
                <Suspense fallback={<PanelFallback />}>
                  <ChangeInspector
                    variant="list"
                    context={changesContext}
                    turnId={changesTurnId}
                    projectRootOverride={changesProjectRoot}
                    onContextChange={onChangesContextChange}
                    className="h-full min-h-0"
                    onRevealInEditor={handleRevealChangeFile}
                    requestedPath={changesFocusPath}
                    onRequestedPathConsumed={() => setChangesFocusPath(null)}
                  />
                </Suspense>
                <div
                  role="separator"
                  aria-orientation="vertical"
                  aria-label={t('inspectorResizeSplit')}
                  className="ds-no-drag absolute inset-y-0 right-0 z-20 w-2 translate-x-1/2 cursor-col-resize touch-none"
                  onPointerDown={beginChangesListResize}
                />
              </div>
            ) : null}

            <div
              className={`relative min-h-0 min-w-0 flex-col overflow-hidden ${
                terminalMaximized ? 'hidden' : 'flex flex-1'
              }`}
            >
              <div
                className={
                  showChangesDiff
                    ? 'pointer-events-none invisible absolute inset-0'
                    : 'flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden'
                }
                aria-hidden={showChangesDiff || undefined}
              >
                <Suspense fallback={<PanelFallback />}>
                  <WorkspaceEditorPanel
                    workspaceRoot={workspaceRoot}
                    blocks={blocks}
                    hideTree={editorHideTree}
                  />
                </Suspense>
              </div>
              {showChangesDiff ? (
                <div className="ds-ide-changes-stage flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
                  <Suspense fallback={<PanelFallback />}>
                    <ChangeInspector
                      variant="diff"
                      context={changesContext}
                      turnId={changesTurnId}
                      projectRootOverride={changesProjectRoot}
                      className="h-full min-h-0"
                      requestedPath={changesFocusPath}
                      onRequestedPathConsumed={() => setChangesFocusPath(null)}
                    />
                  </Suspense>
                </div>
              ) : null}
            </div>

          {chatRailVisible ? (
            <aside
              className={`ds-ide-chat-rail relative flex h-full min-h-0 flex-col bg-ds-canvas ${
                terminalMaximized ? 'min-w-0 flex-1' : 'shrink-0'
              }`}
              style={terminalMaximized ? undefined : { width: chatRailWidth }}
            >
              {/* Same seam pattern as WorkbenchRightSidebar: the panel border is
                  the only visible divider; the resize hit-target stays invisible
                  so we never get a double/offset vertical rule. */}
              {terminalMaximized ? null : (
              <div
                role="separator"
                aria-orientation="vertical"
                aria-label={t('ideChatRailResize')}
                aria-valuemin={IDE_CHAT_RAIL_MIN_WIDTH}
                aria-valuemax={IDE_CHAT_RAIL_MAX_WIDTH}
                aria-valuenow={chatRailWidth}
                tabIndex={0}
                className="ds-ide-chat-rail-handle ds-no-drag absolute inset-y-0 left-0 z-30 w-2 -translate-x-1/2 cursor-col-resize touch-none"
                onPointerDown={beginChatRailResize}
                onDoubleClick={() => {
                  setChatRailWidth(IDE_CHAT_RAIL_DEFAULT_WIDTH)
                  persistIdeChatRailWidth(IDE_CHAT_RAIL_DEFAULT_WIDTH)
                }}
                onKeyDown={(event) => {
                  let next: number | null = null
                  if (event.key === 'ArrowLeft') next = chatRailWidth + 24
                  if (event.key === 'ArrowRight') next = chatRailWidth - 24
                  if (event.key === 'Home') next = IDE_CHAT_RAIL_MIN_WIDTH
                  if (event.key === 'End') next = IDE_CHAT_RAIL_MAX_WIDTH
                  if (next === null) return
                  event.preventDefault()
                  const clamped = clampIdeChatRailWidth(next)
                  setChatRailWidth(clamped)
                  persistIdeChatRailWidth(clamped)
                }}
              />
              )}
              <div className="ds-ide-chat-rail__surface flex h-full min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
                {chatRail}
              </div>
            </aside>
          ) : null}
        </div>
      </div>
      {quickOpenOpen ? (
        <IdeQuickOpenPalette
          workspaceRoot={workspaceRoot}
          onSelectFile={handleQuickOpenFile}
          onClose={() => setQuickOpenOpen(false)}
        />
      ) : null}
    </div>
  )
}
