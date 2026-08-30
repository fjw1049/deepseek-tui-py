import type {
  CSSProperties,
  PointerEvent as ReactPointerEvent,
  ReactElement,
  RefObject
} from 'react'
import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore
} from 'react'
import { useTranslation } from 'react-i18next'
import { useShallow } from 'zustand/react/shallow'
import type { ChatBlock } from '../agent/types'
import { useChatStore } from '../store/chat-store'
import { extractLatestTurnDevPreviewUrls } from '../lib/dev-preview-detection'
import {
  extractLatestTurnHtmlPreviewPaths
} from '../lib/html-preview-detection'
import { isHtmlPreviewPath } from '@shared/html-preview'
import type { PreviewElementPick } from '../lib/preview-element-picker'
import { PREVIEW_PICK_MAX, upsertPreviewPick } from '../lib/preview-pick-message'
import type { Notice } from './extensions/marketplace-shared'
import {
  WORKSPACE_FILE_PREVIEW_EVENT,
  type WorkspaceFilePreviewDetail
} from '../lib/workspace-file-preview'
import { openWorkspaceFilePreferInApp, uniqueWorkspaceRoots } from '../lib/open-workspace-file'
import {
  OPEN_PREVIEW_URL_EVENT,
  type OpenPreviewUrlDetail
} from '../lib/open-preview-url'
import { normalizeBrowseUrlInput } from '@shared/dev-preview-url'
import {
  persistRightSidebarCollapsed,
  persistRightSidebarOpen,
  persistRightSidebarTab,
  readStoredRightSidebarTab,
  type RightSidebarTab
} from '../lib/right-sidebar-state'
import {
  persistLayoutMode,
  type IdeCenterTab,
  type WorkbenchLayoutMode
} from '../lib/workbench-layout-mode'
import {
  closeAllTerminalSessions,
  createTerminalSessionForWorkspace,
  useTerminalSessionStore
} from '../store/terminal-session-store'
import { useWorkspaceEditorStore } from '../store/workspace-editor-store'
import { useWorkspaceFsWatch } from '../hooks/use-workspace-fs-watch'
import {
  isChatsWorkspace,
  isClawWorkspacePath,
  isInternalTemporaryWorkspace,
  normalizeWorkspaceRoot,
  resolveActiveThreadWorkspace,
  resolveThreadFilesystemRoot
} from '../lib/workspace-path'
import { workspaceLabelFromPath } from '../lib/workspace-label'
import { EDITOR_CLOSE_ACTIVE_TAB_EVENT, IDE_QUICK_OPEN_EVENT } from '../lib/workspace-editor-events'
import {
  isShortcutEnabled,
  requestOpenApprovalPolicyMenu,
  requestOpenSidebarSearch
} from '../lib/shortcuts-runtime'
import {
  findMatchedShortcut,
  isEditableKeyboardTarget
} from '@shared/shortcuts'
import { AppTerminalPanel } from './AppTerminalPanel'
import { Sidebar } from './chat/Sidebar'
import { SidebarExpandDroplet } from './chat/SidebarExpandDroplet'
import { OperationContextDock } from './chat/OperationContextDock'
import { MessageTimeline } from './chat/MessageTimeline'
import { ComposerStage } from './chat/ComposerStage'
import { SimpleEmptyPrompt } from './chat/SimpleEmptyPrompt'
import { getEmptyHomeLayout, subscribeAppearance } from '../lib/apply-appearance'
import { ConnectionStatusBar } from './ConnectionStatusBar'
import { DefaultEditorPicker } from './DefaultEditorPicker'
import { SessionHeader } from './SessionHeader'
import { IdeChatRailHeader } from './ide/IdeChatRailHeader'
import { RuntimeDiagnosticsDialog } from './RuntimeDiagnosticsDialog'
import {
  RightSidebarToggleButton,
  WorkbenchRightSidebar
} from './right-sidebar/WorkbenchRightSidebar'
import { IdeWorkspaceLayout } from './ide/IdeWorkspaceLayout'

const MarketplaceView = lazy(() =>
  import('./extensions/MarketplaceView').then((module) => ({ default: module.MarketplaceView }))
)
const AutomationCenter = lazy(() =>
  import('./automation/AutomationCenter').then((module) => ({ default: module.AutomationCenter }))
)
const ChannelCenter = lazy(() =>
  import('./channels/ChannelCenter').then((module) => ({ default: module.ChannelCenter }))
)
const KanbanView = lazy(() =>
  import('./kanban/KanbanView').then((module) => ({ default: module.KanbanView }))
)
const SettingsView = lazy(() =>
  import('./SettingsView').then((module) => ({ default: module.SettingsView }))
)

const LEFT_PANEL_WIDTH_KEY = 'deepseekgui.layout.leftSidebarWidth'
const LEFT_PANEL_COLLAPSED_KEY = 'deepseekgui.layout.leftSidebarCollapsed'
const RIGHT_PANEL_WIDTH_KEY = 'deepseekgui.layout.rightInspectorWidth'
const BOTTOM_TERMINAL_HEIGHT_KEY = 'deepseekgui.layout.bottomTerminalHeight'
const LEFT_PANEL_DEFAULT = 272
const RIGHT_CONTEXT_DEFAULT = 272
const BOTTOM_TERMINAL_DEFAULT = 260
const BOTTOM_TERMINAL_MIN = 140
const BOTTOM_TERMINAL_MAX = 720
const RIGHT_PANEL_DEFAULT = RIGHT_CONTEXT_DEFAULT
const RIGHT_PANEL_HALF_RATIO = 0.5
const LEFT_PANEL_MIN = 236
const LEFT_PANEL_MAX = 500
const RIGHT_PANEL_MIN = 260
const MAIN_MIN_WIDTH = 560
const SHELL_ITEM_GAP = 8
const CHAT_HIDE_THRESHOLD = 48

function clampWidth(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

function readStoredWidth(key: string, fallback: number): number {
  try {
    const raw = window.localStorage.getItem(key)
    if (!raw) return fallback
    const parsed = Number(raw)
    if (!Number.isFinite(parsed)) return fallback
    return Math.round(parsed)
  } catch {
    return fallback
  }
}

function measureMainWidth(
  shellWidth: number,
  leftVisible: boolean,
  leftWidth: number
): number {
  const sideGap = leftVisible ? SHELL_ITEM_GAP : 0
  return Math.max(0, shellWidth - (leftVisible ? leftWidth : 0) - sideGap)
}

function resolveRightPanelLayout(
  mainWidth: number,
  requestedRight: number
): { rightWidth: number; chatHidden: boolean } {
  const maxRight = Math.max(RIGHT_PANEL_MIN, mainWidth)
  const clamped = clampWidth(requestedRight, RIGHT_PANEL_MIN, maxRight)
  const remainingChat = mainWidth - clamped
  if (remainingChat <= CHAT_HIDE_THRESHOLD) {
    return { rightWidth: mainWidth, chatHidden: true }
  }
  return { rightWidth: clamped, chatHidden: false }
}

function resolveLeftPanelWidth(
  shellWidth: number,
  requestedLeft: number,
  rightPanelVisible: boolean
): number {
  const maxLeft = rightPanelVisible
    ? Math.min(
        LEFT_PANEL_MAX,
        Math.max(LEFT_PANEL_MIN, shellWidth - SHELL_ITEM_GAP - RIGHT_PANEL_MIN)
      )
    : Math.min(LEFT_PANEL_MAX, Math.max(LEFT_PANEL_MIN, shellWidth - SHELL_ITEM_GAP - MAIN_MIN_WIDTH))
  return clampWidth(requestedLeft, LEFT_PANEL_MIN, maxLeft)
}

function fitWorkbenchWidths(
  containerWidth: number,
  leftWidth: number,
  rightWidth: number,
  panels: { leftPanelVisible: boolean; rightPanelVisible: boolean },
  mainRowWidth?: number | null
): { left: number; right: number; chatHidden: boolean } {
  const left = panels.leftPanelVisible
    ? resolveLeftPanelWidth(containerWidth, leftWidth, panels.rightPanelVisible)
    : clampWidth(leftWidth, LEFT_PANEL_MIN, LEFT_PANEL_MAX)

  if (!panels.rightPanelVisible) {
    return { left, right: clampWidth(rightWidth, RIGHT_PANEL_MIN, containerWidth), chatHidden: false }
  }

  const mainWidth =
    mainRowWidth ?? measureMainWidth(containerWidth, panels.leftPanelVisible, left)
  const resolved = resolveRightPanelLayout(mainWidth, rightWidth)
  return { left, right: resolved.rightWidth, chatHidden: resolved.chatHidden }
}

function resolveHalfRightWidth(mainWidth: number): number {
  const maxSplit = Math.max(RIGHT_PANEL_MIN, mainWidth - CHAT_HIDE_THRESHOLD - 1)
  return clampWidth(Math.round(mainWidth * RIGHT_PANEL_HALF_RATIO), RIGHT_PANEL_MIN, maxSplit)
}

function readMainRowWidth(
  shellRef: RefObject<HTMLDivElement | null>,
  mainRowRef: RefObject<HTMLDivElement | null>,
  leftVisible: boolean,
  leftWidth: number
): number {
  const measuredMain = mainRowRef.current?.clientWidth ?? null
  if (measuredMain != null) return measuredMain
  const containerWidth = shellRef.current?.clientWidth ?? window.innerWidth
  return measureMainWidth(containerWidth, leftVisible, leftWidth)
}

function persistWidth(key: string, width: number): void {
  try {
    window.localStorage.setItem(key, String(Math.round(width)))
  } catch {
    /* ignore persistence failures */
  }
}

function readStoredBoolean(key: string, fallback: boolean): boolean {
  try {
    const raw = window.localStorage.getItem(key)
    if (raw === '1') return true
    if (raw === '0') return false
  } catch {
    /* ignore persistence failures */
  }
  return fallback
}

function persistBoolean(key: string, value: boolean): void {
  try {
    window.localStorage.setItem(key, value ? '1' : '0')
  } catch {
    /* ignore persistence failures */
  }
}

export function Workbench(): ReactElement {
  const { t } = useTranslation('common')
  const {
    threads,
    activeThreadId,
    selectThread,
    createThread,
    chooseWorkspace,
    activateWorkspace,
    hiddenWorkspacePaths,
    blocks,
    liveReasoning,
    liveAssistant,
    error,
    runtimeErrorDetail,
    busy,
    route,
    workspaceRoot,
    runtimeConnection,
    setRoute,
    openSettings,
    setError,
    sendMessage,
    queuedMessages,
    removeQueuedMessage,
    withdrawQueuedMessage,
    sendQueuedMessageNow,
    interrupt,
    probeRuntime,
    composerModel,
    composerPickList,
    setComposerModel,
    composerMode: mode,
    setComposerMode: setMode,
    deleteThread,
    archiveThread,
    forkThread,
    compactActiveThread
  } = useChatStore(
    useShallow((s) => ({
      threads: s.threads,
      activeThreadId: s.activeThreadId,
      selectThread: s.selectThread,
      createThread: s.createThread,
      chooseWorkspace: s.chooseWorkspace,
      activateWorkspace: s.activateWorkspace,
      hiddenWorkspacePaths: s.hiddenWorkspacePaths,
      blocks: s.blocks,
      liveReasoning: s.liveReasoning,
      liveAssistant: s.liveAssistant,
      error: s.error,
      runtimeErrorDetail: s.runtimeErrorDetail,
      busy: s.busy,
      route: s.route,
      workspaceRoot: s.workspaceRoot,
      runtimeConnection: s.runtimeConnection,
      setRoute: s.setRoute,
      openSettings: s.openSettings,
      setError: s.setError,
      sendMessage: s.sendMessage,
      queuedMessages: s.queuedMessages,
      removeQueuedMessage: s.removeQueuedMessage,
      withdrawQueuedMessage: s.withdrawQueuedMessage,
      sendQueuedMessageNow: s.sendQueuedMessageNow,
      interrupt: s.interrupt,
      probeRuntime: s.probeRuntime,
      composerModel: s.composerModel,
      composerPickList: s.composerPickList,
      setComposerModel: s.setComposerModel,
      composerMode: s.composerMode,
      setComposerMode: s.setComposerMode,
      deleteThread: s.deleteThread,
      archiveThread: s.archiveThread,
      forkThread: s.forkThread,
      compactActiveThread: s.compactActiveThread
    }))
  )
  useWorkspaceFsWatch()
  const [input, setInput] = useState('')
  // Cold start always lands on the main chat shell: left rail expanded, no IDE
  // mode, no right tool panel (editor / changes / terminal / browser). Widths
  // and the last right-sidebar tab still persist for when the user opens them.
  const [rightSidebarOpen, setRightSidebarOpen] = useState(false)
  const [rightSidebarCollapsed, setRightSidebarCollapsed] = useState(false)
  const [rightSidebarTab, setRightSidebarTab] = useState<RightSidebarTab>(readStoredRightSidebarTab)
  const openEditorFile = useWorkspaceEditorStore((s) => s.openFile)
  const [leftSidebarWidth, setLeftSidebarWidth] = useState(() =>
    readStoredWidth(LEFT_PANEL_WIDTH_KEY, LEFT_PANEL_DEFAULT)
  )
  const [leftSidebarCollapsed, setLeftSidebarCollapsed] = useState(false)
  const [rightSidebarWidth, setRightSidebarWidth] = useState(() =>
    readStoredWidth(RIGHT_PANEL_WIDTH_KEY, RIGHT_CONTEXT_DEFAULT)
  )
  const [bottomTerminalOpen, setBottomTerminalOpen] = useState(false)
  const [ideTerminalMaximized, setIdeTerminalMaximized] = useState(false)
  const [bottomTerminalHeight, setBottomTerminalHeight] = useState(() =>
    clampWidth(
      readStoredWidth(BOTTOM_TERMINAL_HEIGHT_KEY, BOTTOM_TERMINAL_DEFAULT),
      BOTTOM_TERMINAL_MIN,
      BOTTOM_TERMINAL_MAX
    )
  )
  const [runtimeDiagnosticsOpen, setRuntimeDiagnosticsOpen] = useState(false)
  const [chatColumnHidden, setChatColumnHidden] = useState(false)
  const [layoutMode, setLayoutMode] = useState<WorkbenchLayoutMode>('chat')
  const [requestedIdeCenterTab, setRequestedIdeCenterTab] = useState<IdeCenterTab | null>(null)
  const [changesFocusPath, setChangesFocusPath] = useState<string | null>(null)
  // Transparent pointer shield shown during panel drags: without it, pointer
  // events over the webview/iframe panels are swallowed by the guest process
  // and the window-level resize listeners starve (drag freezes, then jumps).
  const [resizeShieldCursor, setResizeShieldCursor] = useState<
    'col-resize' | 'row-resize' | null
  >(null)
  const stageInsetClass = 'px-5 md:px-10 lg:px-16 xl:px-24'
  const conversationInsetClass = 'px-3 md:px-5 lg:px-6 xl:px-8'
  const operationConversationInsetClass = 'pl-3 md:pl-5 lg:pl-6 xl:pl-8 pr-0'
  const emptyStageInsetClass = 'px-2 md:px-3 lg:px-4 xl:px-5'

  const shellRef = useRef<HTMLDivElement | null>(null)
  const mainRowRef = useRef<HTMLDivElement | null>(null)
  const draftByThread = useRef<Record<string, string>>({})
  const prevThreadId = useRef<string | null>(null)
  const previewThreadId = useRef<string | null>(activeThreadId)
  const inputRef = useRef('')
  const autoOpenedPreviewUrlRef = useRef<string | null>(null)
  const previewAutoOpenSuppressedRef = useRef(false)
  const lastAutoDiagnosticsErrorRef = useRef('')
  const devPreviewBlocks = useMemo<ChatBlock[]>(() => {
    const liveText = liveAssistant.trim()
    if (!liveText) return blocks
    return [
      ...blocks,
      {
        kind: 'assistant',
        id: '__live-assistant-dev-preview',
        text: liveAssistant
      }
    ]
  }, [blocks, liveAssistant])
  const detectedDevPreviewUrls = useMemo(
    () => extractLatestTurnDevPreviewUrls(devPreviewBlocks),
    [devPreviewBlocks]
  )
  const latestDevPreviewUrl = detectedDevPreviewUrls[0] ?? null
  const detectedHtmlPreviewPaths = useMemo(
    () => extractLatestTurnHtmlPreviewPaths(devPreviewBlocks),
    [devPreviewBlocks]
  )
  const latestHtmlPreviewPath = detectedHtmlPreviewPaths[0] ?? null
  const [workspacePreviewUrl, setWorkspacePreviewUrl] = useState<string | null>(null)
  const [workspacePreviewPath, setWorkspacePreviewPath] = useState<string | null>(null)
  const [browsePreviewUrl, setBrowsePreviewUrl] = useState<string | null>(null)
  const [composerFocusRequestId, setComposerFocusRequestId] = useState(0)
  const [pendingPreviewPicks, setPendingPreviewPicks] = useState<PreviewElementPick[]>([])
  const [previewPickNotice, setPreviewPickNotice] = useState<Notice | null>(null)
  const [previewPickNoticeNonce, setPreviewPickNoticeNonce] = useState(0)
  const [htmlPreviewError, setHtmlPreviewError] = useState<string | null>(null)
  const preferredPreviewUrl = browsePreviewUrl ?? workspacePreviewUrl ?? latestDevPreviewUrl
  const preferredPreviewFilePath = browsePreviewUrl
    ? null
    : workspacePreviewUrl
      ? workspacePreviewPath
      : null

  const hasStartedConversation =
    blocks.length > 0 ||
    busy ||
    liveAssistant.trim().length > 0 ||
    liveReasoning.trim().length > 0

  const stageCentered = !hasStartedConversation
  const emptyHomeLayout = useSyncExternalStore(subscribeAppearance, getEmptyHomeLayout)
  const activeWorkspaceRoot = useMemo(
    () => resolveActiveThreadWorkspace(activeThreadId, threads, workspaceRoot),
    [activeThreadId, threads, workspaceRoot]
  )
  const ideProjectOptions = useMemo(() => {
    const paths = new Set<string>()
    const active = normalizeWorkspaceRoot(activeWorkspaceRoot)
    if (active) paths.add(active)
    for (const thread of threads) {
      const path = normalizeWorkspaceRoot(thread.workspace)
      if (!path) continue
      if (isInternalTemporaryWorkspace(path) || isClawWorkspacePath(path) || isChatsWorkspace(path)) {
        continue
      }
      if (
        hiddenWorkspacePaths.some(
          (hidden) => normalizeWorkspaceRoot(hidden).toLowerCase() === path.toLowerCase()
        )
      ) {
        continue
      }
      paths.add(path)
    }
    return [...paths]
      .sort((left, right) =>
        workspaceLabelFromPath(left).localeCompare(workspaceLabelFromPath(right), undefined, {
          sensitivity: 'base'
        })
      )
      .map((path) => ({
        path,
        name: workspaceLabelFromPath(path)
      }))
  }, [activeWorkspaceRoot, hiddenWorkspacePaths, threads])
  const handleSelectIdeProject = useCallback(
    (workspacePath: string): void => {
      void activateWorkspace(workspacePath)
    },
    [activateWorkspace]
  )
  const handleBrowseIdeProject = useCallback((): void => {
    void chooseWorkspace()
  }, [chooseWorkspace])
  const simpleEmptyHome =
    stageCentered &&
    emptyHomeLayout === 'simple' &&
    runtimeConnection === 'ready' &&
    activeWorkspaceRoot.trim().length > 0
  const threadFilesystemRoot = useMemo(
    () => resolveThreadFilesystemRoot(activeThreadId, threads, workspaceRoot),
    [activeThreadId, threads, workspaceRoot]
  )
  const showHtmlPreviewCard =
    route === 'chat' &&
    latestHtmlPreviewPath !== null &&
    threadFilesystemRoot.trim().length > 0
  const showOperationColumn =
    route === 'chat' && activeWorkspaceRoot.trim().length > 0 && !stageCentered
  const showDefaultEditorPicker =
    route === 'chat' && activeWorkspaceRoot.trim().length > 0
  // Panel header already owns close/maximize when the sidebar is fully open —
  // keep the topbar control only for closed / collapsed-strip (open) entry.
  const rightPanelVisible = rightSidebarOpen && !rightSidebarCollapsed
  const ideModeActive =
    route === 'chat' && layoutMode === 'ide' && activeWorkspaceRoot.trim().length > 0
  // IDE rail is too narrow for Overview / GitHub cards — always simple empty home.
  const ideSimpleEmptyHome =
    ideModeActive &&
    runtimeConnection === 'ready' &&
    !busy &&
    blocks.length === 0 &&
    !liveAssistant &&
    !liveReasoning
  // IDE mode is editor-first: hide the projects/threads rail entirely (Synara
  // Editor view does the same). Keep the user's chat-mode collapse preference
  // in `leftSidebarCollapsed` so exiting IDE restores it.
  const leftSidebarHidden = leftSidebarCollapsed || ideModeActive
  const showRightSidebarToggle =
    route === 'chat' &&
    activeWorkspaceRoot.trim().length > 0 &&
    !rightPanelVisible &&
    !ideModeActive
  const showTopbarRightActions = showDefaultEditorPicker || showRightSidebarToggle
  const topbarRightPaddingClass = showTopbarRightActions
    ? showDefaultEditorPicker && showRightSidebarToggle
      ? 'pr-[9.5rem] sm:pr-[10rem]'
      : showDefaultEditorPicker
        ? 'pr-[5.25rem]'
        : 'pr-9 sm:pr-10'
    : ''
  const operationColumnActive = showOperationColumn && !rightSidebarOpen
  const terminalSidebarOpen =
    rightSidebarOpen && rightSidebarTab === 'terminal' && !rightSidebarCollapsed
  const chatColumnInsetClass = useMemo(() => {
    if (stageCentered) return emptyStageInsetClass
    if (operationColumnActive) return `${operationConversationInsetClass} ds-chat-inset-with-operation`
    return conversationInsetClass
  }, [conversationInsetClass, emptyStageInsetClass, operationColumnActive, operationConversationInsetClass, stageCentered])

  const handleSend = (text: string): void => {
    const v = text.trim()
    if (!v) return
    setInput('')
    void sendMessage(v, mode)
  }

  const handleComposerFork = async (): Promise<void> => {
    if (!activeThreadId) return
    await forkThread(activeThreadId)
  }

  const handleComposerOpenDiff = (): void => {
    if (layoutMode === 'ide') {
      setRequestedIdeCenterTab('changes')
      return
    }
    setRightSidebarOpen(true)
    setRightSidebarCollapsed(false)
    setRightSidebarTab('changes')
  }

  const openRightSidebar = useCallback((tab: RightSidebarTab): void => {
    setRightSidebarOpen(true)
    setRightSidebarCollapsed(false)
    setRightSidebarTab(tab)
  }, [])

  const openInAppEditorSurface = useCallback(
    async (
      path: string,
      workspaceRoot: string,
      line?: number,
      column?: number
    ): Promise<boolean> => {
      if (layoutMode === 'ide') {
        setRequestedIdeCenterTab('files')
      } else {
        openRightSidebar('editor')
      }
      return openEditorFile(path, workspaceRoot, line, column)
    },
    [layoutMode, openEditorFile, openRightSidebar]
  )

  const openFileInEditor = useCallback(
    (path: string, line?: number, options?: { review?: boolean }): void => {
      if (options?.review) {
        window.dispatchEvent(
          new CustomEvent('deepseekgui:open-changes-panel', { detail: { path } })
        )
        if (layoutMode !== 'ide') return
      }
      void openWorkspaceFilePreferInApp(
        { path, ...(line && line > 0 ? { line } : {}) },
        uniqueWorkspaceRoots(activeWorkspaceRoot, threadFilesystemRoot),
        openInAppEditorSurface
      ).then((result) => {
        if (result === 'none') setError(`${t('fileReferenceOpenFailed')}: ${path}`)
      })
    },
    [activeWorkspaceRoot, layoutMode, openInAppEditorSurface, setError, t, threadFilesystemRoot]
  )

  const enterIdeMode = useCallback((): void => {
    if (!activeWorkspaceRoot.trim()) {
      setError(t('ideNeedsWorkspace'))
      return
    }
    // IDE mode owns the center stage; clear chat-mode maximize so the two
    // layout systems never fight over chatColumnHidden.
    setChatColumnHidden(false)
    setLayoutMode('ide')
    persistLayoutMode('ide')
  }, [activeWorkspaceRoot, setError, t])

  const exitIdeMode = useCallback((): void => {
    setLayoutMode('chat')
    persistLayoutMode('chat')
  }, [])

  const closeRightSidebar = useCallback((): void => {
    setRightSidebarOpen(false)
    setRightSidebarCollapsed(false)
    setChatColumnHidden(false)
  }, [])

  const toggleRightSidebar = useCallback((): void => {
    if (!rightSidebarOpen) {
      setRightSidebarOpen(true)
      setRightSidebarCollapsed(false)
      return
    }
    if (rightSidebarCollapsed) {
      setRightSidebarCollapsed(false)
      return
    }
    setRightSidebarOpen(false)
    setChatColumnHidden(false)
  }, [rightSidebarCollapsed, rightSidebarOpen])

  const toggleTerminalPanel = useCallback((): void => {
    if (!activeWorkspaceRoot.trim()) return
    if (bottomTerminalOpen) {
      setIdeTerminalMaximized(false)
      useTerminalSessionStore.getState().setSplitSessionId(null)
      setBottomTerminalOpen(false)
      return
    }
    // Bottom terminal and the right-sidebar terminal tab share one global xterm
    // session store, so only one may mount at a time: hand the mount over by
    // steering the sidebar off its terminal tab before opening the bottom panel.
    if (terminalSidebarOpen) closeRightSidebar()
    setBottomTerminalOpen(true)
  }, [activeWorkspaceRoot, bottomTerminalOpen, closeRightSidebar, terminalSidebarOpen])

  const toggleRightSidebarMaximize = useCallback((): void => {
    const mainWidth = readMainRowWidth(
      shellRef,
      mainRowRef,
      !leftSidebarHidden,
      leftSidebarWidth
    )
    if (chatColumnHidden) {
      setRightSidebarWidth(resolveHalfRightWidth(mainWidth))
      setChatColumnHidden(false)
      return
    }
    setRightSidebarWidth(mainWidth)
    setChatColumnHidden(true)
  }, [chatColumnHidden, leftSidebarHidden, leftSidebarWidth])

  useEffect(() => {
    inputRef.current = input
  }, [input])

  // IDE mode requires a bound workspace; fall back to chat if the root disappears
  // (thread switch / cleared project) so we never render an empty IDE shell.
  useEffect(() => {
    if (layoutMode !== 'ide') return
    if (activeWorkspaceRoot.trim()) return
    setLayoutMode('chat')
    persistLayoutMode('chat')
  }, [activeWorkspaceRoot, layoutMode])

  // Scroll perf: flag the shell while any surface is actively scrolling so CSS
  // can drop the expensive backdrop-filter blur (re-rasterized every frame in
  // Electron). Capture-phase catches every scroll container at once; the blur
  // is restored ~160ms after scrolling stops.
  useEffect(() => {
    const shell = shellRef.current
    if (!shell) return
    let timer: number | null = null
    const onScroll = (): void => {
      shell.classList.add('is-scrolling')
      if (timer !== null) window.clearTimeout(timer)
      timer = window.setTimeout(() => shell.classList.remove('is-scrolling'), 160)
    }
    document.addEventListener('scroll', onScroll, { passive: true, capture: true })
    return () => {
      document.removeEventListener('scroll', onScroll, { capture: true } as EventListenerOptions)
      if (timer !== null) window.clearTimeout(timer)
    }
  }, [])

  useEffect(() => {
    persistWidth(LEFT_PANEL_WIDTH_KEY, leftSidebarWidth)
  }, [leftSidebarWidth])

  useEffect(() => {
    persistBoolean(LEFT_PANEL_COLLAPSED_KEY, leftSidebarCollapsed)
  }, [leftSidebarCollapsed])

  useEffect(() => {
    persistWidth(RIGHT_PANEL_WIDTH_KEY, rightSidebarWidth)
  }, [rightSidebarWidth])

  useEffect(() => {
    persistRightSidebarOpen(rightSidebarOpen)
  }, [rightSidebarOpen])

  useEffect(() => {
    persistRightSidebarTab(rightSidebarTab)
  }, [rightSidebarTab])

  useEffect(() => {
    persistRightSidebarCollapsed(rightSidebarCollapsed)
  }, [rightSidebarCollapsed])

  // Scrub stale IDE / open-panel flags written by older builds so storage matches
  // the cold-start shell even if something else reads those keys later.
  useEffect(() => {
    persistLayoutMode('chat')
    persistRightSidebarOpen(false)
    persistRightSidebarCollapsed(false)
  }, [])

  useEffect(() => {
    persistWidth(BOTTOM_TERMINAL_HEIGHT_KEY, bottomTerminalHeight)
  }, [bottomTerminalHeight])

  // Enforce single-mount for the shared terminal store: whenever the sidebar
  // shows its own terminal tab, or no workspace is active, drop the bottom
  // panel so only one AppTerminalPanel is ever mounted.
  useEffect(() => {
    if (terminalSidebarOpen || !activeWorkspaceRoot.trim()) {
      setBottomTerminalOpen(false)
    }
  }, [activeWorkspaceRoot, terminalSidebarOpen])

  const prevRightSidebarOpenRef = useRef(rightSidebarOpen)
  useEffect(() => {
    const prev = prevRightSidebarOpenRef.current
    prevRightSidebarOpenRef.current = rightSidebarOpen
    if (!prev && rightSidebarOpen && !rightSidebarCollapsed) {
      const mainWidth = readMainRowWidth(
        shellRef,
        mainRowRef,
        !leftSidebarHidden,
        leftSidebarWidth
      )
      setRightSidebarWidth(resolveHalfRightWidth(mainWidth))
      setChatColumnHidden(false)
    }
  }, [leftSidebarHidden, leftSidebarWidth, rightSidebarCollapsed, rightSidebarOpen])

  useEffect(() => {
    const openEditorTarget = (
      path: string,
      projectRoots: string[],
      line?: number,
      column?: number
    ): void => {
      void openWorkspaceFilePreferInApp(
        { path, ...(line && line > 0 ? { line } : {}), ...(column && column > 0 ? { column } : {}) },
        projectRoots,
        openInAppEditorSurface
      ).then((result) => {
        if (result === 'none') setError(`${t('fileReferenceOpenFailed')}: ${path}`)
      })
    }

    const onPreview = (event: Event): void => {
      const detail = (event as CustomEvent<WorkspaceFilePreviewDetail>).detail
      if (!detail?.path) return
      const roots = uniqueWorkspaceRoots(
        activeWorkspaceRoot,
        threadFilesystemRoot,
        detail.workspaceRoot
      )
      const root = roots[0] ?? ''
      if (isHtmlPreviewPath(detail.path) && root) {
        if (layoutMode === 'ide') {
          openEditorTarget(detail.path, roots, detail.line, detail.column)
          return
        }
        openRightSidebar('preview')
        void (async () => {
          const api = window.dsGui?.getWorkspaceHtmlPreviewUrl
          if (typeof api !== 'function') {
            console.error(
              '[html-preview] getWorkspaceHtmlPreviewUrl missing — restart Workbench to load the new preload bridge'
            )
            return
          }
          try {
            const result = await api({
              path: detail.path,
              workspaceRoot: root
            })
            if (!result.ok) {
              console.error('[html-preview]', result.message)
              openEditorTarget(detail.path, roots, detail.line, detail.column)
              return
            }
            setBrowsePreviewUrl(null)
            setWorkspacePreviewUrl(result.url)
            setWorkspacePreviewPath(detail.path)
          } catch (error) {
            console.error('[html-preview] failed to resolve preview URL', error)
            openEditorTarget(detail.path, roots, detail.line, detail.column)
          }
        })()
        return
      }
      openEditorTarget(detail.path, roots, detail.line, detail.column)
    }

    window.addEventListener(WORKSPACE_FILE_PREVIEW_EVENT, onPreview)
    return () => window.removeEventListener(WORKSPACE_FILE_PREVIEW_EVENT, onPreview)
  }, [
    activeWorkspaceRoot,
    layoutMode,
    openEditorFile,
    openInAppEditorSurface,
    openRightSidebar,
    setError,
    t,
    threadFilesystemRoot
  ])

  useEffect(() => {
    const onOpenChanges = (event: Event): void => {
      const path = (event as CustomEvent<{ path?: string }>).detail?.path
      if (typeof path === 'string' && path.trim()) setChangesFocusPath(path.trim())
      if (layoutMode === 'ide') {
        setRequestedIdeCenterTab('changes')
        return
      }
      openRightSidebar('changes')
    }
    window.addEventListener('deepseekgui:open-changes-panel', onOpenChanges)
    return () => window.removeEventListener('deepseekgui:open-changes-panel', onOpenChanges)
  }, [layoutMode, openRightSidebar])

  useEffect(() => {
    const onOpenPreviewUrl = (event: Event): void => {
      const url = (event as CustomEvent<OpenPreviewUrlDetail>).detail?.url
      const normalized = typeof url === 'string' ? normalizeBrowseUrlInput(url) : null
      if (!normalized) return
      previewAutoOpenSuppressedRef.current = false
      setBrowsePreviewUrl(normalized)
      openRightSidebar('preview')
    }
    window.addEventListener(OPEN_PREVIEW_URL_EVENT, onOpenPreviewUrl)
    return () => window.removeEventListener(OPEN_PREVIEW_URL_EVENT, onOpenPreviewUrl)
  }, [openRightSidebar])

  useEffect(() => {
    if (previewThreadId.current === activeThreadId) return
    previewThreadId.current = activeThreadId
    autoOpenedPreviewUrlRef.current = null
    previewAutoOpenSuppressedRef.current = false
    setWorkspacePreviewUrl(null)
    setWorkspacePreviewPath(null)
    setBrowsePreviewUrl(null)
    setPendingPreviewPicks([])
    setHtmlPreviewError(null)
    if (rightSidebarOpen && rightSidebarTab === 'preview') {
      closeRightSidebar()
    }
  }, [activeThreadId, closeRightSidebar, rightSidebarOpen, rightSidebarTab])

  useEffect(() => {
    if (!latestDevPreviewUrl || route !== 'chat') return
    if (previewAutoOpenSuppressedRef.current) return
    if (autoOpenedPreviewUrlRef.current === latestDevPreviewUrl) return
    // Restored threads often already contain a preview URL — do not reopen the
    // browser panel on cold start / idle navigation. Only auto-open when a new
    // URL appears while a turn is actively running.
    if (!busy) {
      autoOpenedPreviewUrlRef.current = latestDevPreviewUrl
      return
    }
    autoOpenedPreviewUrlRef.current = latestDevPreviewUrl
    openRightSidebar('preview')
  }, [busy, latestDevPreviewUrl, openRightSidebar, route])

  useEffect(() => {
    if (activeWorkspaceRoot.trim()) return
    closeAllTerminalSessions()
  }, [activeWorkspaceRoot])

  useEffect(() => {
    const prev = prevThreadId.current
    prevThreadId.current = activeThreadId
    if (prev != null && prev !== activeThreadId) {
      draftByThread.current[prev] = inputRef.current
    }
    if (activeThreadId != null && activeThreadId !== prev) {
      setInput(draftByThread.current[activeThreadId] ?? '')
    }
    if (activeThreadId == null) {
      setInput('')
    }
  }, [activeThreadId])

  // Periodic background probe — keeps connected state fresh and
  // attempts to recover when the runtime is offline.
  useEffect(() => {
    let cancelled = false
    const tick = (): void => {
      if (cancelled) return
      void useChatStore.getState().probeRuntime('background')
    }
    const onlineDelay = 30_000
    const offlineDelay = 6_000
    let id = window.setTimeout(function loop() {
      tick()
      if (cancelled) return
      const next = useChatStore.getState().runtimeConnection === 'ready' ? onlineDelay : offlineDelay
      id = window.setTimeout(loop, next)
    }, onlineDelay)
    return () => {
      cancelled = true
      window.clearTimeout(id)
    }
  }, [])

  useEffect(() => {
    if (runtimeConnection !== 'offline' || !runtimeErrorDetail) return
    const lowered = runtimeErrorDetail.toLowerCase()
    const shouldOpen =
      !lowered.includes('missing_api_key') &&
      (lowered.includes('config') ||
        lowered.includes('toml') ||
        lowered.includes('deepseek') ||
        lowered.includes('runtime') ||
        lowered.includes('serve') ||
        lowered.includes('spawn') ||
        lowered.includes('fetch failed'))
    if (!shouldOpen || lastAutoDiagnosticsErrorRef.current === runtimeErrorDetail) return
    lastAutoDiagnosticsErrorRef.current = runtimeErrorDetail
    setRuntimeDiagnosticsOpen(true)
  }, [runtimeConnection, runtimeErrorDetail])

  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      const matched = findMatchedShortcut(e)
      if (!matched) return
      // saveFile is handled inside the workspace editor (scoped to the pane).
      if (matched.id === 'saveFile') return
      if (!isShortcutEnabled(matched.id)) return
      if (matched.ignoreWhenTyping && isEditableKeyboardTarget(e.target)) return

      if (matched.id === 'newConversation') {
        e.preventDefault()
        setRoute('chat')
        // Mirror the New Agent button: project-active → inherit; else → chats.
        // Temp chats live in default_workspace (non-empty), so test isChats.
        const state = useChatStore.getState()
        const activeThread = state.activeThreadId
          ? state.threads.find((thread) => thread.id === state.activeThreadId)
          : undefined
        const root = resolveActiveThreadWorkspace(
          state.activeThreadId,
          state.threads,
          state.workspaceRoot
        )
        if (root.trim().length > 0 && !isChatsWorkspace(activeThread?.workspace)) {
          void createThread({ workspaceRoot: root })
        } else {
          state.setChatsCollapsed(false)
          void createThread({ chats: true })
        }
        return
      }

      if (matched.id === 'searchConversations') {
        e.preventDefault()
        setLeftSidebarCollapsed(false)
        requestOpenSidebarSearch()
        return
      }

      if (matched.id === 'openKanban') {
        e.preventDefault()
        setLeftSidebarCollapsed(false)
        setRoute('kanban')
        return
      }

      if (matched.id === 'importProject') {
        e.preventDefault()
        if (ideModeActive) {
          window.dispatchEvent(new CustomEvent(IDE_QUICK_OPEN_EVENT))
          return
        }
        void chooseWorkspace()
        return
      }

      if (matched.id === 'toggleLeftSidebar') {
        e.preventDefault()
        setLeftSidebarCollapsed((current) => !current)
        return
      }

      if (matched.id === 'toggleRightPanel') {
        e.preventDefault()
        toggleRightSidebar()
        return
      }

      if (matched.id === 'approvalPolicyMenu') {
        e.preventDefault()
        setRoute('chat')
        requestOpenApprovalPolicyMenu()
        return
      }

      if (matched.id === 'openTerminal') {
        const editorFocused = Boolean(
          (e.target instanceof Element &&
            e.target.closest('.ds-workspace-editor-pane, .monaco-editor')) ||
            document.activeElement?.closest('.ds-workspace-editor-pane, .monaco-editor')
        )
        if (ideModeActive && editorFocused) {
          e.preventDefault()
          window.dispatchEvent(new CustomEvent(EDITOR_CLOSE_ACTIVE_TAB_EVENT))
          return
        }
        e.preventDefault()
        setRoute('chat')
        toggleTerminalPanel()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [
    chooseWorkspace,
    createThread,
    ideModeActive,
    setRoute,
    toggleRightSidebar,
    toggleTerminalPanel
  ])

  useEffect(() => {
    const sync = (): void => {
      const containerWidth = shellRef.current?.clientWidth ?? window.innerWidth
      const measuredMain = mainRowRef.current?.clientWidth ?? null
      const next = fitWorkbenchWidths(
        containerWidth,
        leftSidebarWidth,
        rightSidebarWidth,
        {
          leftPanelVisible: !leftSidebarHidden,
          rightPanelVisible
        },
        measuredMain
      )
      if (next.left !== leftSidebarWidth) setLeftSidebarWidth(next.left)
      // Fill-width is an explicit maximize. Opening the left rail shrinks
      // the main row, and the fit helper then sees "room for chat" against
      // the stored right width — that would un-hide a white chat sliver
      // beside the editor. Keep fill-width while the right panel is still
      // filling; if it closes or collapses, fall through so chat returns.
      if (chatColumnHidden && rightPanelVisible) return
      if (rightPanelVisible && next.right !== rightSidebarWidth) {
        setRightSidebarWidth(next.right)
      }
      // IDE mode owns chat visibility; never let the chat-mode fit helper hide it.
      if (!ideModeActive) setChatColumnHidden(next.chatHidden)
    }
    sync()
    window.addEventListener('resize', sync)
    return () => window.removeEventListener('resize', sync)
  }, [
    chatColumnHidden,
    ideModeActive,
    leftSidebarHidden,
    leftSidebarWidth,
    rightPanelVisible,
    rightSidebarWidth
  ])

  const openThread = (id: string): void => {
    setRoute('chat')
    void selectThread(id)
  }

  const openThreadTerminal = async (id: string): Promise<void> => {
    setRoute('chat')
    if (activeThreadId !== id) await selectThread(id)
    openRightSidebar('terminal')
  }

  const startNewChat = (): void => {
    setRoute('chat')
    // Context-aware New Agent / ⌘N: when a real project is active the new
    // agent belongs to that project (inherit its workspace); otherwise it is
    // a temporary (Chats) thread. Reveal the Chats section so the new
    // temporary thread is visible even if it was collapsed.
    // Note: a temporary chat's workspace is the shared DEFAULT_WORKSPACE_ROOT,
    // which is non-empty, so test `isChatsWorkspace` (not just an empty root).
    const activeThread = activeThreadId
      ? threads.find((thread) => thread.id === activeThreadId)
      : undefined
    const inProject =
      activeWorkspaceRoot.trim().length > 0 && !isChatsWorkspace(activeThread?.workspace)
    if (inProject) {
      void createThread({ workspaceRoot: activeWorkspaceRoot })
    } else {
      useChatStore.getState().setChatsCollapsed(false)
      void createThread({ chats: true })
    }
  }

  // Workspace-section "+" must always create a temporary Chats thread.
  // Reusing startNewChat here mis-routes into the active project, so the
  // new session appears under Projects and looks like Workspace "+" did nothing.
  const startNewChatsThread = (): void => {
    setRoute('chat')
    useChatStore.getState().setChatsCollapsed(false)
    void createThread({ chats: true })
  }

  const startNewChatInWorkspace = (workspaceRoot: string): void => {
    setRoute('chat')
    void createThread({ workspaceRoot })
  }

  const closeRightSidebarPanel = (): void => {
    if (rightSidebarTab === 'preview') {
      previewAutoOpenSuppressedRef.current = true
    }
    closeRightSidebar()
  }

  const expandLeftSidebar = (): void => {
    setLeftSidebarCollapsed(false)
  }

  const sidebarWrapWidth = leftSidebarWidth

  const togglePreviewPanel = (): void => {
    if (rightSidebarOpen && rightSidebarTab === 'preview' && !rightSidebarCollapsed) {
      previewAutoOpenSuppressedRef.current = true
      closeRightSidebar()
      return
    }
    previewAutoOpenSuppressedRef.current = false
    openRightSidebar('preview')
  }

  const openHtmlPreview = useCallback((): void => {
    const path = latestHtmlPreviewPath?.trim()
    if (!path) {
      console.error('[html-preview] missing html path')
      return
    }
    if (layoutMode === 'ide') {
      const ideRoot = (threadFilesystemRoot || activeWorkspaceRoot).trim()
      setRequestedIdeCenterTab('files')
      if (ideRoot) void openEditorFile(path, ideRoot)
      return
    }
    // Prefer the thread's real filesystem root; if missing and the HTML path
    // is absolute, fall back to that file's parent directory so preview still
    // works when UI "project" state was blanked for temporary workspaces.
    let root = threadFilesystemRoot.trim()
    if (!root && (path.startsWith('/') || /^[A-Za-z]:[\\/]/.test(path))) {
      const normalized = path.replace(/\\/g, '/')
      const slash = normalized.lastIndexOf('/')
      root = slash > 0 ? normalized.slice(0, slash) : ''
    }
    void (async () => {
      const api = window.dsGui?.getWorkspaceHtmlPreviewUrl
      if (typeof api !== 'function') {
        console.error(
          '[html-preview] getWorkspaceHtmlPreviewUrl missing — fully restart Workbench (preload must reload)'
        )
        return
      }
      try {
        const result = await api({
          path,
          ...(root ? { workspaceRoot: root } : {})
        })
        if (!result.ok) {
          console.error('[html-preview]', result.message, { path, root })
          openRightSidebar('preview')
          setBrowsePreviewUrl(null)
          setWorkspacePreviewUrl(null)
          setWorkspacePreviewPath(null)
          setHtmlPreviewError(result.message)
          return
        }
        setHtmlPreviewError(null)
        setBrowsePreviewUrl(null)
        setWorkspacePreviewUrl(result.url)
        setWorkspacePreviewPath(path)
        openRightSidebar('preview')
      } catch (error) {
        console.error('[html-preview] failed to resolve preview URL', error)
        openRightSidebar('preview')
        setHtmlPreviewError(
          error instanceof Error ? error.message : 'Failed to open HTML preview'
        )
      }
    })()
  }, [
    activeWorkspaceRoot,
    latestHtmlPreviewPath,
    layoutMode,
    openEditorFile,
    openRightSidebar,
    threadFilesystemRoot
  ])

  const clearWorkspacePreviewUrl = useCallback((): void => {
    setWorkspacePreviewUrl(null)
    setWorkspacePreviewPath(null)
  }, [])

  const clearHtmlPreviewError = useCallback((): void => {
    setHtmlPreviewError(null)
  }, [])

  const handlePreviewPick = useCallback(
    (pick: PreviewElementPick): void => {
      // Keep the textarea for the short user request; context rides as chips
      // and is expanded to JSON only on send. Same selector toggles off.
      setPendingPreviewPicks((current) => {
        const result = upsertPreviewPick(current, pick)
        if (result.kind === 'limit') {
          setPreviewPickNotice({
            tone: 'info',
            message: t('composerPreviewPickLimit', { count: PREVIEW_PICK_MAX })
          })
          setPreviewPickNoticeNonce((n) => n + 1)
        }
        return result.picks
      })
      setComposerFocusRequestId((current) => current + 1)
    },
    [t]
  )

  const removePendingPreviewPick = useCallback((index: number): void => {
    setPendingPreviewPicks((current) => current.filter((_, i) => i !== index))
  }, [])

  const clearPendingPreviewPicks = useCallback((): void => {
    setPendingPreviewPicks([])
  }, [])

  const htmlPreviewAction = useMemo(
    () =>
      showHtmlPreviewCard && latestHtmlPreviewPath
        ? { path: latestHtmlPreviewPath, onOpen: openHtmlPreview }
        : null,
    [showHtmlPreviewCard, latestHtmlPreviewPath, openHtmlPreview]
  )

  const beginLeftResize = (event: ReactPointerEvent<HTMLDivElement>): void => {
    if (leftSidebarHidden || event.button !== 0) return
    event.preventDefault()
    const startX = event.clientX
    const startLeft = leftSidebarWidth
    const startRight = rightSidebarWidth
    const prevCursor = document.body.style.cursor
    const prevUserSelect = document.body.style.userSelect
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
    // Suspend the collapse transition while dragging so the width tracks the
    // pointer 1:1 instead of easing behind it.
    const wrapEl = (event.currentTarget as HTMLElement).closest('.ds-workbench-sidebar-wrap')
    wrapEl?.classList.add('is-resizing')
    setResizeShieldCursor('col-resize')

    const onMove = (moveEvent: PointerEvent): void => {
      const containerWidth = shellRef.current?.clientWidth ?? window.innerWidth
      const measuredMain = mainRowRef.current?.clientWidth ?? null
      const delta = moveEvent.clientX - startX
      const next = fitWorkbenchWidths(
        containerWidth,
        startLeft + delta,
        startRight,
        {
          leftPanelVisible: true,
          rightPanelVisible
        },
        measuredMain
      )
      setLeftSidebarWidth(next.left)
      if (rightPanelVisible && !chatColumnHidden) {
        if (next.right !== rightSidebarWidth) setRightSidebarWidth(next.right)
        setChatColumnHidden(next.chatHidden)
      }
    }

    const onUp = (): void => {
      document.body.style.cursor = prevCursor
      document.body.style.userSelect = prevUserSelect
      wrapEl?.classList.remove('is-resizing')
      setResizeShieldCursor(null)
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
    }

    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
  }

  const beginRightResize = (event: ReactPointerEvent<HTMLDivElement>): void => {
    if (event.button !== 0 || !rightPanelVisible) return
    event.preventDefault()
    const startX = event.clientX
    const startLeft = leftSidebarWidth
    const startRight = rightSidebarWidth
    const prevCursor = document.body.style.cursor
    const prevUserSelect = document.body.style.userSelect
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
    setResizeShieldCursor('col-resize')

    const onMove = (moveEvent: PointerEvent): void => {
      const containerWidth = shellRef.current?.clientWidth ?? window.innerWidth
      const measuredMain = mainRowRef.current?.clientWidth ?? null
      const delta = moveEvent.clientX - startX
      const next = fitWorkbenchWidths(
        containerWidth,
        startLeft,
        startRight - delta,
        {
          leftPanelVisible: !leftSidebarHidden,
          rightPanelVisible: true
        },
        measuredMain
      )
      if (next.left !== leftSidebarWidth) setLeftSidebarWidth(next.left)
      setRightSidebarWidth(next.right)
      setChatColumnHidden(next.chatHidden)
    }

    const onUp = (): void => {
      document.body.style.cursor = prevCursor
      document.body.style.userSelect = prevUserSelect
      setResizeShieldCursor(null)
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
    }

    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
  }

  const beginBottomTerminalResize = (event: ReactPointerEvent<HTMLDivElement>): void => {
    if (event.button !== 0) return
    event.preventDefault()
    const startY = event.clientY
    const startHeight = bottomTerminalHeight
    const prevCursor = document.body.style.cursor
    const prevUserSelect = document.body.style.userSelect
    document.body.style.cursor = 'row-resize'
    document.body.style.userSelect = 'none'
    setResizeShieldCursor('row-resize')

    const onMove = (moveEvent: PointerEvent): void => {
      // Handle sits on the panel's top edge, so dragging up (negative delta)
      // grows the panel.
      const delta = startY - moveEvent.clientY
      setBottomTerminalHeight(
        clampWidth(startHeight + delta, BOTTOM_TERMINAL_MIN, BOTTOM_TERMINAL_MAX)
      )
    }

    const onUp = (): void => {
      document.body.style.cursor = prevCursor
      document.body.style.userSelect = prevUserSelect
      setResizeShieldCursor(null)
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
    }

    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
  }

  return (
    <div
      ref={shellRef}
      className="ds-workbench-shell ds-drag relative flex h-full min-h-0 w-full min-w-0"
      data-ide-mode={ideModeActive ? '' : undefined}
      style={
        {
          '--ds-sidebar-width': `${leftSidebarHidden ? 0 : sidebarWrapWidth}px`
        } as CSSProperties
      }
    >
      {resizeShieldCursor !== null ? (
        <div
          aria-hidden
          className="fixed inset-0 z-[100]"
          style={{ cursor: resizeShieldCursor }}
        />
      ) : null}
      {/* Fixed expand control — same window coords as the sidebar collapse
          trigger, so the toggle never jumps when the rail opens/closes.
          Hidden in IDE mode: that layout has no projects/threads rail. */}
      {leftSidebarCollapsed && !ideModeActive ? (
        <SidebarExpandDroplet onExpand={expandLeftSidebar} />
      ) : null}
      {/* Stays mounted while collapsed so the offcanvas slide can animate: the
          wrap's width shrinks to 0 while the fixed-width inner column slides
          left, both on the same 300ms curve (Synara sidebar gap + container). */}
      <div
        className="ds-workbench-sidebar-wrap relative min-h-0 shrink-0"
        data-collapsed={leftSidebarHidden ? '' : undefined}
        aria-hidden={leftSidebarHidden}
        inert={leftSidebarHidden || undefined}
        style={{ width: leftSidebarHidden ? 0 : sidebarWrapWidth }}
      >
        <div
          className="ds-workbench-sidebar-slide absolute inset-y-0 left-0"
          style={{
            width: sidebarWrapWidth,
            transform: leftSidebarHidden ? 'translateX(-100%)' : 'translateX(0)'
          }}
        >
          <Sidebar
            threads={threads}
            activeThreadId={activeThreadId}
            runtimeReady={runtimeConnection === 'ready'}
            onSelectThread={openThread}
            onOpenThreadTerminal={openThreadTerminal}
            onDeleteThread={deleteThread}
            onArchiveThread={archiveThread}
            onNewChat={startNewChat}
            onNewChatsThread={startNewChatsThread}
            onNewChatInWorkspace={startNewChatInWorkspace}
            onOpenSettings={(section) => openSettings(section)}
            onCollapseSidebar={() => setLeftSidebarCollapsed(true)}
          />
        </div>
        <div
          role="separator"
          aria-orientation="vertical"
          aria-label={t('sidebarResize')}
          className="ds-no-drag group absolute inset-y-0 right-0 z-30 w-2 translate-x-1/2 cursor-col-resize"
          onPointerDown={beginLeftResize}
        >
          {/* No visible line: the content card's seam ring is the only divider (Synara). */}
        </div>
      </div>

      <main
        className={`ds-workbench-main ds-drag ds-stage-surface relative flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden ${
          route === 'marketplace' ? 'px-0' : ''
        }`}
      >
        {route === 'settings' ? (
          <Suspense fallback={<div className="h-full bg-transparent" />}>
            <SettingsView />
          </Suspense>
        ) : route === 'marketplace' ? (
          <Suspense fallback={<div className="h-full bg-transparent" />}>
            <MarketplaceView />
          </Suspense>
        ) : route === 'kanban' ? (
          <Suspense fallback={<div className="h-full bg-transparent" />}>
            <KanbanView
              onOpenThread={openThread}
              onOpenThreadTerminal={openThreadTerminal}
            />
          </Suspense>
        ) : route === 'automation' ? (
          <Suspense fallback={<div className="h-full bg-transparent" />}>
            <AutomationCenter
              runtimeReady={runtimeConnection === 'ready'}
              workspaceRoot={activeWorkspaceRoot}
              onOpenRuntimeSettings={() => openSettings('general')}
            />
          </Suspense>
        ) : route === 'channels' ? (
          <Suspense fallback={<div className="h-full bg-transparent" />}>
            <ChannelCenter runtimeReady={runtimeConnection === 'ready'} />
          </Suspense>
        ) : (
          <>
        {error && !(runtimeConnection !== 'ready' && !activeThreadId) && (
          <div className="ds-no-drag shrink-0 border-b border-amber-200/70 bg-[rgba(255,248,235,0.82)] backdrop-blur-lg dark:border-amber-800/50 dark:bg-amber-950/35">
            <div className={`${stageInsetClass} flex w-full min-w-0 items-start justify-between gap-3 py-3`}>
              <p className="min-w-0 flex-1 text-[14px] leading-6 text-amber-950 dark:text-amber-100">
                {error}
              </p>
              <div className="flex shrink-0 items-center gap-2">
                {runtimeConnection !== 'ready' ? (
                  <>
                    <button
                      type="button"
                      className="rounded-lg border border-amber-300/70 bg-white px-3 py-1 text-[12px] font-medium text-amber-950 transition hover:bg-amber-100/80 dark:border-amber-700/60 dark:bg-amber-900/20 dark:text-amber-100 dark:hover:bg-amber-900/40"
                      onClick={() => void probeRuntime('user')}
                    >
                      {t('retryConnection')}
                    </button>
                    <button
                      type="button"
                      className="rounded-lg border border-amber-300/70 bg-white px-3 py-1 text-[12px] font-medium text-amber-950 transition hover:bg-amber-100/80 dark:border-amber-700/60 dark:bg-amber-900/20 dark:text-amber-100 dark:hover:bg-amber-900/40"
                      onClick={() => setRuntimeDiagnosticsOpen(true)}
                    >
                      {t('runtimeDiagnosticsButton')}
                    </button>
                    <button
                      type="button"
                      className="rounded-lg px-3 py-1 text-[12px] font-medium text-amber-900/80 transition hover:bg-amber-50/70 dark:text-amber-100 dark:hover:bg-amber-900/30"
                      onClick={() => openSettings('general')}
                    >
                      {t('openSettings')}
                    </button>
                  </>
                ) : null}
              </div>
            </div>
          </div>
        )}

        {ideModeActive ? (
          <div ref={mainRowRef} className="flex min-h-0 min-w-0 flex-1 flex-col">
            <IdeWorkspaceLayout
              workspaceRoot={activeWorkspaceRoot}
              blocks={blocks}
              projectLabel={workspaceLabelFromPath(activeWorkspaceRoot)}
              projectOptions={ideProjectOptions}
              onSelectProject={handleSelectIdeProject}
              onBrowseProject={handleBrowseIdeProject}
              onExitIdeMode={exitIdeMode}
              onOpenFileInEditor={openFileInEditor}
              requestedCenterTab={requestedIdeCenterTab}
              onRequestedCenterTabConsumed={() => setRequestedIdeCenterTab(null)}
              terminalMaximized={bottomTerminalOpen && ideTerminalMaximized}
              chatRail={
                <div className="flex h-full min-h-0 min-w-0 flex-col">
                  <IdeChatRailHeader
                    busy={busy}
                    terminalOpen={bottomTerminalOpen}
                    terminalMaximized={ideTerminalMaximized}
                    onNewChat={() => {
                      setIdeTerminalMaximized(false)
                      useTerminalSessionStore.getState().setSplitSessionId(null)
                      setBottomTerminalOpen(false)
                      if (activeWorkspaceRoot.trim()) {
                        startNewChatInWorkspace(activeWorkspaceRoot)
                      } else {
                        startNewChat()
                      }
                    }}
                    onNewTerminal={() => {
                      if (!activeWorkspaceRoot.trim()) return
                      if (bottomTerminalOpen) {
                        void createTerminalSessionForWorkspace(activeWorkspaceRoot)
                        return
                      }
                      if (useTerminalSessionStore.getState().sessions.length === 0) {
                        useTerminalSessionStore.setState({ hasStartedInitialSession: false })
                      }
                      toggleTerminalPanel()
                    }}
                    onCloseTerminal={() => {
                      setIdeTerminalMaximized(false)
                      useTerminalSessionStore.getState().setSplitSessionId(null)
                      setBottomTerminalOpen(false)
                    }}
                    onToggleMaximize={() => setIdeTerminalMaximized((current) => !current)}
                  />
                  {bottomTerminalOpen && activeWorkspaceRoot.trim().length > 0 ? (
                    <AppTerminalPanel
                      workspaceRoot={activeWorkspaceRoot}
                      mountSurface="bottom"
                      mountActive
                      visible
                      hideTabs
                      onClose={() => setBottomTerminalOpen(false)}
                      className="min-h-0 w-full flex-1 border-0"
                    />
                  ) : (
                  <div className="flex min-h-0 min-w-0 flex-1 flex-col">
                    {ideSimpleEmptyHome ? (
                      <div className="flex min-h-0 min-w-0 flex-1 flex-col justify-center pl-[1.15rem] pr-[0.95rem]">
                        <SimpleEmptyPrompt />
                      </div>
                    ) : (
                      <MessageTimeline
                        blocks={blocks}
                        liveReasoning={liveReasoning}
                        live={liveAssistant}
                        activeThreadId={activeThreadId}
                        runtimeConnection={runtimeConnection}
                        stageCentered={false}
                        useChatStageWidth={false}
                        forceSimpleEmptyHome
                        onRetryConnection={() => void probeRuntime('user')}
                        onOpenSettings={() => openSettings('general')}
                        onOpenDiagnostics={() => setRuntimeDiagnosticsOpen(true)}
                        onSelectSuggestion={(text) => setInput(text)}
                        htmlPreviewAction={htmlPreviewAction}
                        onOpenWorkspaceFile={openFileInEditor}
                      />
                    )}
                    <div className="mx-auto flex w-full shrink-0 px-[0.95rem] pl-[1.15rem] pb-3 pt-0">
                      <ComposerStage
                        input={input}
                        setInput={setInput}
                        mode={mode}
                        setMode={setMode}
                        busy={busy}
                        runtimeReady={runtimeConnection === 'ready'}
                        hasActiveThread={Boolean(activeThreadId)}
                        useChatStageWidth={false}
                        compactChrome
                        composerModel={composerModel}
                        composerPickList={composerPickList}
                        onComposerModelChange={(modelId) => {
                          setComposerModel(modelId)
                        }}
                        onSend={handleSend}
                        onCompact={compactActiveThread}
                        onFork={handleComposerFork}
                        onOpenDiff={handleComposerOpenDiff}
                        queuedMessages={queuedMessages}
                        onRemoveQueuedMessage={removeQueuedMessage}
                        onWithdrawQueuedMessage={withdrawQueuedMessage}
                        onSendQueuedMessageNow={(id) => void sendQueuedMessageNow(id)}
                        onInterrupt={() => void interrupt()}
                        focusRequestId={composerFocusRequestId}
                        previewPicks={pendingPreviewPicks}
                        onRemovePreviewPick={removePendingPreviewPick}
                        onClearPreviewPicks={clearPendingPreviewPicks}
                        flashNotice={previewPickNotice}
                        flashNoticeNonce={previewPickNoticeNonce}
                      />
                    </div>
                  </div>
                  )}
                </div>
              }
            />
          </div>
        ) : (
        <div ref={mainRowRef} className="flex min-h-0 flex-1">
          <div className={`min-h-0 min-w-0 flex-1 flex-col ${chatColumnHidden ? 'hidden' : 'flex'}`}>
          <section className="ds-drag flex min-h-0 min-w-0 flex-1 flex-col">
            <header className="ds-workbench-topbar ds-surface-divider relative z-10 shrink-0 bg-transparent">
              <div className="ds-workbench-topbar__inner flex w-full min-w-0 items-center justify-between gap-2">
                <div className="flex h-7 min-w-0 flex-1 items-center overflow-hidden">
                  <SessionHeader compact className="min-w-0" />
                </div>
                <div className={`flex h-7 shrink-0 items-center gap-1.5 ${topbarRightPaddingClass}`}>
                  <ConnectionStatusBar compact />
                  {busy ? (
                    <span className="inline-flex shrink-0 rounded-full bg-amber-500/16 px-1.5 py-px text-[10px] font-semibold leading-4 text-amber-950 dark:text-amber-100">
                      {t('running')}
                    </span>
                  ) : null}
                </div>
              </div>
              {showTopbarRightActions ? (
                <div className="ds-workbench-topbar__right-actions ds-no-drag">
                  {showDefaultEditorPicker ? <DefaultEditorPicker /> : null}
                  {showRightSidebarToggle ? (
                    <RightSidebarToggleButton
                      open={false}
                      onClick={toggleRightSidebar}
                    />
                  ) : null}
                </div>
              ) : null}
            </header>
            <div className="ds-chat-main-row relative flex min-h-0 min-w-0 flex-1">
              {!chatColumnHidden ? (
              <div
                className={`ds-chat-main-track flex min-h-0 min-w-0 flex-1 flex-col ${chatColumnInsetClass}`}
              >
            <div className="flex min-h-0 min-w-0 flex-1 flex-col">
              {stageCentered ? (
                <div
                  className={`ds-empty-stage flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden ${
                    simpleEmptyHome ? 'ds-empty-stage--simple' : ''
                  }`}
                >
                  <div
                    className={`ds-empty-stage-frame relative flex min-h-0 min-w-0 flex-1 flex-col ${
                      simpleEmptyHome ? 'justify-center' : ''
                    }`}
                  >
                    {!simpleEmptyHome ? (
                      <div className="ds-chat-stage ds-empty-stage-hero min-h-0 flex-1 overflow-y-auto">
                        <MessageTimeline
                          blocks={blocks}
                          liveReasoning={liveReasoning}
                          live={liveAssistant}
                          activeThreadId={activeThreadId}
                          runtimeConnection={runtimeConnection}
                          stageCentered={stageCentered}
                          useChatStageWidth={false}
                          onRetryConnection={() => void probeRuntime('user')}
                          onOpenSettings={() => openSettings('general')}
                          onOpenDiagnostics={() => setRuntimeDiagnosticsOpen(true)}
                          onSelectSuggestion={(text) => setInput(text)}
                          htmlPreviewAction={htmlPreviewAction}
                          onOpenWorkspaceFile={openFileInEditor}
                        />
                      </div>
                    ) : null}
                    <div
                      className={
                        simpleEmptyHome
                          ? 'ds-simple-empty-cluster shrink-0'
                          : 'ds-chat-stage ds-empty-stage-composer mt-auto shrink-0'
                      }
                    >
                      {simpleEmptyHome ? <SimpleEmptyPrompt /> : null}
                      <div
                        className={
                          simpleEmptyHome
                            ? 'ds-chat-stage ds-empty-stage-composer'
                            : 'contents'
                        }
                      >
                        <ComposerStage
                          input={input}
                          setInput={setInput}
                          mode={mode}
                          setMode={setMode}
                          busy={busy}
                          runtimeReady={runtimeConnection === 'ready'}
                          hasActiveThread={Boolean(activeThreadId)}
                          stageCentered={stageCentered}
                          useChatStageWidth={false}
                          composerModel={composerModel}
                          composerPickList={composerPickList}
                          onComposerModelChange={(modelId) => {
                            setComposerModel(modelId)
                          }}
                          onSend={handleSend}
                          onCompact={compactActiveThread}
                          onFork={handleComposerFork}
                          onOpenDiff={handleComposerOpenDiff}
                          queuedMessages={queuedMessages}
                          onRemoveQueuedMessage={removeQueuedMessage}
                          onWithdrawQueuedMessage={withdrawQueuedMessage}
                          onSendQueuedMessageNow={(id) => void sendQueuedMessageNow(id)}
                          onInterrupt={() => void interrupt()}
                          focusRequestId={composerFocusRequestId}
                          previewPicks={pendingPreviewPicks}
                          onRemovePreviewPick={removePendingPreviewPick}
                          onClearPreviewPicks={clearPendingPreviewPicks}
                          flashNotice={previewPickNotice}
                          flashNoticeNonce={previewPickNoticeNonce}
                        />
                      </div>
                    </div>
                  </div>
                </div>
              ) : operationColumnActive ? (
                <div className="ds-chat-operation-band min-h-0 min-w-0 flex-1">
                  <div className="ds-chat-operation-band__dialogue ds-dialogue-gutter flex min-h-0 min-w-0 flex-1 flex-col">
                    <MessageTimeline
                      blocks={blocks}
                      liveReasoning={liveReasoning}
                      live={liveAssistant}
                      activeThreadId={activeThreadId}
                      runtimeConnection={runtimeConnection}
                      stageCentered={stageCentered}
                      withOperationColumn
                      onRetryConnection={() => void probeRuntime('user')}
                      onOpenSettings={() => openSettings('general')}
                      onOpenDiagnostics={() => setRuntimeDiagnosticsOpen(true)}
                      onSelectSuggestion={(text) => setInput(text)}
                      htmlPreviewAction={htmlPreviewAction}
                      onOpenWorkspaceFile={openFileInEditor}
                    />
                    {showOperationColumn ? (
                      <div className="ds-dialogue-gutter shrink-0 pb-2 md:hidden">
                        <OperationContextDock
                          onOpenChanges={handleComposerOpenDiff}
                          onEnterIdeMode={enterIdeMode}
                          previewActive={rightSidebarOpen && rightSidebarTab === 'preview'}
                          terminalPanelOpen={bottomTerminalOpen}
                          terminalPanelEnabled={activeWorkspaceRoot.trim().length > 0}
                          previewEnabled={activeWorkspaceRoot.trim().length > 0}
                          onTogglePreview={togglePreviewPanel}
                          onToggleTerminalPanel={toggleTerminalPanel}
                        />
                      </div>
                    ) : null}
                    <div className="ds-chat-stage mx-auto mb-8 flex w-full shrink-0 -mt-6 pb-0 pt-0">
                      <ComposerStage
                        input={input}
                        setInput={setInput}
                        mode={mode}
                        setMode={setMode}
                        busy={busy}
                        runtimeReady={runtimeConnection === 'ready'}
                        hasActiveThread={Boolean(activeThreadId)}
                        useChatStageWidth={false}
                        composerModel={composerModel}
                        composerPickList={composerPickList}
                        onComposerModelChange={(modelId) => {
                          setComposerModel(modelId)
                        }}
                        onSend={handleSend}
                        onCompact={compactActiveThread}
                        onFork={handleComposerFork}
                        onOpenDiff={handleComposerOpenDiff}
                        queuedMessages={queuedMessages}
                        onRemoveQueuedMessage={removeQueuedMessage}
                        onWithdrawQueuedMessage={withdrawQueuedMessage}
                        onSendQueuedMessageNow={(id) => void sendQueuedMessageNow(id)}
                        onInterrupt={() => void interrupt()}
                        focusRequestId={composerFocusRequestId}
                        previewPicks={pendingPreviewPicks}
                        onRemovePreviewPick={removePendingPreviewPick}
                        onClearPreviewPicks={clearPendingPreviewPicks}
                        flashNotice={previewPickNotice}
                        flashNoticeNonce={previewPickNoticeNonce}
                      />
                    </div>
                  </div>
                  <aside className="ds-operation-rail ds-no-drag hidden h-full min-h-0 shrink-0 md:flex">
                    <div className="ds-operation-rail__scroll min-h-0 flex-1 overflow-y-auto pb-4 pl-0 pr-0 pt-[var(--ds-operation-stack-offset)]">
                      <OperationContextDock
                        onOpenChanges={handleComposerOpenDiff}
                        onEnterIdeMode={enterIdeMode}
                        previewActive={rightSidebarOpen && rightSidebarTab === 'preview'}
                        terminalPanelOpen={bottomTerminalOpen}
                        terminalPanelEnabled={activeWorkspaceRoot.trim().length > 0}
                        previewEnabled={activeWorkspaceRoot.trim().length > 0}
                        onTogglePreview={togglePreviewPanel}
                        onToggleTerminalPanel={toggleTerminalPanel}
                      />
                    </div>
                  </aside>
                </div>
              ) : (
                <div className="ds-chat-stage ds-dialogue-gutter mx-auto flex min-h-0 w-full min-w-0 flex-1 flex-col">
                  <MessageTimeline
                    blocks={blocks}
                    liveReasoning={liveReasoning}
                    live={liveAssistant}
                    activeThreadId={activeThreadId}
                    runtimeConnection={runtimeConnection}
                    stageCentered={stageCentered}
                    onRetryConnection={() => void probeRuntime('user')}
                    onOpenSettings={() => openSettings('general')}
                    onOpenDiagnostics={() => setRuntimeDiagnosticsOpen(true)}
                    onSelectSuggestion={(text) => setInput(text)}
                    htmlPreviewAction={htmlPreviewAction}
                    onOpenWorkspaceFile={openFileInEditor}
                  />
                  <div className="mx-auto mb-8 flex w-full shrink-0 -mt-6 pb-0 pt-0">
                    <ComposerStage
                      input={input}
                      setInput={setInput}
                      mode={mode}
                      setMode={setMode}
                      busy={busy}
                      runtimeReady={runtimeConnection === 'ready'}
                      hasActiveThread={Boolean(activeThreadId)}
                      useChatStageWidth={false}
                      composerModel={composerModel}
                      composerPickList={composerPickList}
                      onComposerModelChange={(modelId) => {
                        setComposerModel(modelId)
                      }}
                      onSend={handleSend}
                      onCompact={compactActiveThread}
                      onFork={handleComposerFork}
                      onOpenDiff={handleComposerOpenDiff}
                      queuedMessages={queuedMessages}
                      onRemoveQueuedMessage={removeQueuedMessage}
                      onWithdrawQueuedMessage={withdrawQueuedMessage}
                      onSendQueuedMessageNow={(id) => void sendQueuedMessageNow(id)}
                      onInterrupt={() => void interrupt()}
                      focusRequestId={composerFocusRequestId}
                      previewPicks={pendingPreviewPicks}
                      onRemovePreviewPick={removePendingPreviewPick}
                      onClearPreviewPicks={clearPendingPreviewPicks}
                      flashNotice={previewPickNotice}
                      flashNoticeNonce={previewPickNoticeNonce}
                    />
                  </div>
                </div>
              )}
            </div>
            </div>
              ) : null}
            </div>
            {bottomTerminalOpen && activeWorkspaceRoot.trim().length > 0 ? (
              <div
                className="ds-bottom-terminal ds-no-drag flex shrink-0 flex-col border-t-2 border-ds-border"
                style={{ height: bottomTerminalHeight }}
              >
                <div
                  role="separator"
                  aria-orientation="horizontal"
                  aria-label={t('terminalPanelResize')}
                  title={t('terminalPanelResize')}
                  className="ds-bottom-terminal__handle ds-no-drag group flex h-2 shrink-0 items-center justify-center cursor-row-resize touch-none select-none"
                  onPointerDown={beginBottomTerminalResize}
                >
                  <span className="pointer-events-none h-0.5 w-8 rounded-full bg-ds-border-strong transition group-hover:w-12 group-hover:bg-ds-accent/70" />
                </div>
                <AppTerminalPanel
                  workspaceRoot={activeWorkspaceRoot}
                  mountSurface="bottom"
                  mountActive
                  visible
                  onClose={() => setBottomTerminalOpen(false)}
                  className="min-h-0 w-full flex-1 border-0"
                />
              </div>
            ) : null}
          </section>
          </div>
          {/* Full-height right panel: sits beside the topbar column so its 44px
              tab header shares one continuous divider line with the topbar and
              its left border runs the card's full height. */}
          <WorkbenchRightSidebar
            open={rightSidebarOpen}
            collapsed={rightSidebarCollapsed}
            tab={rightSidebarTab}
            width={rightSidebarWidth}
            workspaceRoot={activeWorkspaceRoot}
            blocks={blocks}
            changesFocusPath={changesFocusPath}
            onChangesFocusPathConsumed={() => setChangesFocusPath(null)}
            devPreviewBlocks={devPreviewBlocks}
            latestDevPreviewUrl={preferredPreviewUrl}
            preferredPreviewFilePath={preferredPreviewFilePath}
            previewError={htmlPreviewError}
            onPreferredUrlConsumed={clearWorkspacePreviewUrl}
            onPreviewErrorConsumed={clearHtmlPreviewError}
            onPreviewPick={handlePreviewPick}
            onTabChange={setRightSidebarTab}
            onToggleCollapsed={() => setRightSidebarCollapsed((current) => !current)}
            onClose={closeRightSidebarPanel}
            onToggleMaximize={toggleRightSidebarMaximize}
            maximized={chatColumnHidden}
            onBeginResize={beginRightResize}
            onOpenFileInEditor={openFileInEditor}
            fillWidth={chatColumnHidden}
            terminalMountActive={!bottomTerminalOpen}
          />
        </div>
        )}
          </>
        )}
      </main>
      <RuntimeDiagnosticsDialog
        open={runtimeDiagnosticsOpen}
        lastError={runtimeErrorDetail ?? error}
        onClose={() => setRuntimeDiagnosticsOpen(false)}
        onRetry={() => probeRuntime('user')}
        onOpenSettings={() => {
          setRuntimeDiagnosticsOpen(false)
          openSettings('general')
        }}
      />
    </div>
  )
}
