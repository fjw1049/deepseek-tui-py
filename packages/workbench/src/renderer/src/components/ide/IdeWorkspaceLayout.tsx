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
  persistIdeCenterTab,
  persistIdeChatRailWidth,
  readStoredIdeCenterTab,
  readStoredIdeChatRailWidth,
  type IdeCenterTab
} from '../../lib/workbench-layout-mode'
import { workspaceLabelFromPath } from '../../lib/workspace-label'
import { useWorkspaceEditorStore } from '../../store/workspace-editor-store'
import { IdeProjectPicker, type IdeProjectOption } from './IdeProjectPicker'
import { IdeWorkspaceSearchSidebar } from './IdeWorkspaceSearchSidebar'

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
  /** Imperative center-tab request from parent (e.g. open diff from composer). */
  requestedCenterTab?: IdeCenterTab | null
  onRequestedCenterTabConsumed?: () => void
}

type ActivityItem = IdeCenterTab

function PanelFallback(): ReactElement {
  return <div className="h-full w-full bg-ds-sidebar" />
}

function ActivityButton({
  active,
  label,
  children,
  onClick
}: {
  active: boolean
  label: string
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
      className={`inline-flex h-9 w-9 items-center justify-center rounded-md transition ${
        active
          ? 'bg-ds-hover text-ds-ink'
          : 'text-ds-faint hover:bg-ds-hover/55 hover:text-ds-muted'
      }`}
    >
      {children}
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
  requestedCenterTab = null,
  onRequestedCenterTabConsumed
}: Props): ReactElement {
  const { t } = useTranslation('common')
  const openEditorFile = useWorkspaceEditorStore((s) => s.openFile)
  const activeTabPath = useWorkspaceEditorStore((s) => {
    const active = s.tabs.find((tab) => tab.id === s.activeTabId)
    return active?.path ?? null
  })

  const [centerTab, setCenterTab] = useState<IdeCenterTab>(readStoredIdeCenterTab)
  const [searchQuery, setSearchQuery] = useState('')
  const [chatRailVisible, setChatRailVisible] = useState(true)
  const [chatRailWidth, setChatRailWidth] = useState(readStoredIdeChatRailWidth)
  const resizeStateRef = useRef<{
    pointerId: number
    startX: number
    startWidth: number
    pendingWidth: number
  } | null>(null)

  useEffect(() => {
    persistIdeCenterTab(centerTab)
  }, [centerTab])

  useEffect(() => {
    if (!requestedCenterTab) return
    setCenterTab(requestedCenterTab)
    onRequestedCenterTabConsumed?.()
  }, [onRequestedCenterTabConsumed, requestedCenterTab])

  const selectActivity = useCallback((item: ActivityItem) => {
    setCenterTab(item)
  }, [])

  const handleSelectSearchFile = useCallback(
    (path: string) => {
      // Stay on search so the result list remains; the editor (hideTree) opens the hit.
      void openEditorFile(path, workspaceRoot)
    },
    [openEditorFile, workspaceRoot]
  )

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

  const showSearchSidebar = centerTab === 'search'
  // Search owns the left list; keep the editor tree for Files mode.
  const editorHideTree = centerTab === 'search'

  const projectName =
    projectLabel?.trim() ||
    workspaceLabelFromPath(workspaceRoot) ||
    t('ideWorkspaceTitle')
  const projectPath = workspaceRoot.trim()
  const showProjectPicker = Boolean(onSelectProject)

  return (
    <div className="ds-ide-workspace flex h-full min-h-0 min-w-0 flex-1 flex-col bg-ds-main text-ds-ink">
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
              <PanelRightClose className="h-3.5 w-3.5" strokeWidth={1.85} />
              <span className="sr-only">
                {chatRailVisible ? t('ideChatRailHide') : t('ideChatRailShow')}
              </span>
            </button>
          </div>
        </div>
      </header>

      <div className="flex min-h-0 min-w-0 flex-1 overflow-hidden">
        <nav
          className="ds-ide-activity-bar flex w-11 shrink-0 flex-col items-center gap-1 bg-ds-sidebar py-2"
          aria-label={t('ideActivityBarLabel')}
        >
          <ActivityButton
            active={centerTab === 'files'}
            label={t('ideActivityFiles')}
            onClick={() => selectActivity('files')}
          >
            <Folders className="h-4 w-4" strokeWidth={1.85} />
          </ActivityButton>
          <ActivityButton
            active={centerTab === 'changes'}
            label={t('ideActivityChanges')}
            onClick={() => selectActivity('changes')}
          >
            <FileEdit className="h-4 w-4" strokeWidth={1.85} />
          </ActivityButton>
          <ActivityButton
            active={centerTab === 'search'}
            label={t('ideActivitySearch')}
            onClick={() => selectActivity('search')}
          >
            <Search className="h-4 w-4" strokeWidth={1.85} />
          </ActivityButton>
        </nav>

        <div className="flex min-h-0 min-w-0 flex-1 overflow-hidden">
          {showSearchSidebar ? (
            <IdeWorkspaceSearchSidebar
              workspaceRoot={workspaceRoot}
              query={searchQuery}
              onQueryChange={setSearchQuery}
              selectedPath={activeTabPath}
              onSelectFile={handleSelectSearchFile}
            />
          ) : null}

          <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
            <Suspense fallback={<PanelFallback />}>
              {centerTab === 'changes' ? (
                <ChangeInspector
                  blocks={blocks}
                  onOpenFileInEditor={(path, line) => {
                    setCenterTab('files')
                    onOpenFileInEditor(path, line)
                  }}
                />
              ) : (
                <WorkspaceEditorPanel
                  workspaceRoot={workspaceRoot}
                  blocks={blocks}
                  hideTree={editorHideTree}
                />
              )}
            </Suspense>
          </div>

          {chatRailVisible ? (
            <aside
              className="ds-ide-chat-rail relative flex h-full min-h-0 shrink-0 flex-col bg-ds-main"
              style={{ width: chatRailWidth }}
            >
              {/* Same seam pattern as WorkbenchRightSidebar: the panel border is
                  the only visible divider; the resize hit-target stays invisible
                  so we never get a double/offset vertical rule. */}
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
              <div className="ds-ide-chat-rail__surface flex h-full min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
                {chatRail}
              </div>
            </aside>
          ) : null}
        </div>
      </div>
    </div>
  )
}
