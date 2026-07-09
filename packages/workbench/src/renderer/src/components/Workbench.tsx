import type { PointerEvent as ReactPointerEvent, ReactElement, RefObject } from 'react'
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Globe2, PanelLeftOpen } from 'lucide-react'
import { useShallow } from 'zustand/react/shallow'
import type { ChatBlock } from '../agent/types'
import { useChatStore } from '../store/chat-store'
import {
  extractLatestTurnDevPreviewUrls,
  formatDevPreviewUrlLabel
} from '../lib/dev-preview-detection'
import {
  WORKSPACE_FILE_PREVIEW_EVENT,
  type WorkspaceFilePreviewDetail
} from '../lib/workspace-file-preview'
import {
  persistRightSidebarCollapsed,
  persistRightSidebarOpen,
  persistRightSidebarTab,
  readStoredRightSidebarCollapsed,
  readStoredRightSidebarOpen,
  readStoredRightSidebarTab,
  type RightSidebarTab
} from '../lib/right-sidebar-state'
import { closeAllTerminalSessions } from '../store/terminal-session-store'
import { useWorkspaceEditorStore } from '../store/workspace-editor-store'
import { isChatsWorkspace, resolveActiveThreadWorkspace } from '../lib/workspace-path'
import { AppTerminalPanel } from './AppTerminalPanel'
import { Sidebar } from './chat/Sidebar'
import { SidebarExpandDroplet } from './chat/SidebarExpandDroplet'
import { OperationContextDock } from './chat/OperationContextDock'
import { MessageTimeline } from './chat/MessageTimeline'
import { ComposerStage } from './chat/ComposerStage'
import { ConnectionStatusBar } from './ConnectionStatusBar'
import { DefaultEditorPicker } from './DefaultEditorPicker'
import { SessionHeader } from './SessionHeader'
import { RuntimeDiagnosticsDialog } from './RuntimeDiagnosticsDialog'
import {
  RightSidebarToggleButton,
  WorkbenchRightSidebar
} from './right-sidebar/WorkbenchRightSidebar'

const SkillsView = lazy(() =>
  import('./extensions/SkillsView').then((module) => ({ default: module.SkillsView }))
)
const ConnectorsView = lazy(() =>
  import('./extensions/ConnectorsView').then((module) => ({ default: module.ConnectorsView }))
)
const PluginsView = lazy(() =>
  import('./extensions/PluginsView').then((module) => ({ default: module.PluginsView }))
)
const AutomationCenter = lazy(() =>
  import('./automation/AutomationCenter').then((module) => ({ default: module.AutomationCenter }))
)
const ChannelCenter = lazy(() =>
  import('./channels/ChannelCenter').then((module) => ({ default: module.ChannelCenter }))
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
    blocks,
    liveReasoning,
    liveAssistant,
    error,
    runtimeErrorDetail,
    busy,
    route,
    pluginHostRoute,
    workspaceRoot,
    runtimeConnection,
    setRoute,
    openSettings,
    setError,
    sendMessage,
    queuedMessages,
    removeQueuedMessage,
    interrupt,
    probeRuntime,
    composerModel,
    composerPickList,
    setComposerModel,
    deleteThread,
    forkThread,
    compactActiveThread
  } = useChatStore(
    useShallow((s) => ({
      threads: s.threads,
      activeThreadId: s.activeThreadId,
      selectThread: s.selectThread,
      createThread: s.createThread,
      blocks: s.blocks,
      liveReasoning: s.liveReasoning,
      liveAssistant: s.liveAssistant,
      error: s.error,
      runtimeErrorDetail: s.runtimeErrorDetail,
      busy: s.busy,
      route: s.route,
      pluginHostRoute: s.pluginHostRoute,
      workspaceRoot: s.workspaceRoot,
      runtimeConnection: s.runtimeConnection,
      setRoute: s.setRoute,
      openSettings: s.openSettings,
      setError: s.setError,
      sendMessage: s.sendMessage,
      queuedMessages: s.queuedMessages,
      removeQueuedMessage: s.removeQueuedMessage,
      interrupt: s.interrupt,
      probeRuntime: s.probeRuntime,
      composerModel: s.composerModel,
      composerPickList: s.composerPickList,
      setComposerModel: s.setComposerModel,
      deleteThread: s.deleteThread,
      forkThread: s.forkThread,
      compactActiveThread: s.compactActiveThread
    }))
  )
  const [input, setInput] = useState('')
  const [mode, setMode] = useState<import('./chat/FloatingComposer').ComposerMode>('agent')
  const [rightSidebarOpen, setRightSidebarOpen] = useState(readStoredRightSidebarOpen)
  const [rightSidebarCollapsed, setRightSidebarCollapsed] = useState(readStoredRightSidebarCollapsed)
  const [rightSidebarTab, setRightSidebarTab] = useState<RightSidebarTab>(readStoredRightSidebarTab)
  const openEditorFile = useWorkspaceEditorStore((s) => s.openFile)
  const [leftSidebarWidth, setLeftSidebarWidth] = useState(() =>
    readStoredWidth(LEFT_PANEL_WIDTH_KEY, LEFT_PANEL_DEFAULT)
  )
  const [leftSidebarCollapsed, setLeftSidebarCollapsed] = useState(() =>
    readStoredBoolean(LEFT_PANEL_COLLAPSED_KEY, false)
  )
  const [rightSidebarWidth, setRightSidebarWidth] = useState(() =>
    readStoredWidth(RIGHT_PANEL_WIDTH_KEY, RIGHT_CONTEXT_DEFAULT)
  )
  const [bottomTerminalOpen, setBottomTerminalOpen] = useState(false)
  const [bottomTerminalHeight, setBottomTerminalHeight] = useState(() =>
    clampWidth(
      readStoredWidth(BOTTOM_TERMINAL_HEIGHT_KEY, BOTTOM_TERMINAL_DEFAULT),
      BOTTOM_TERMINAL_MIN,
      BOTTOM_TERMINAL_MAX
    )
  )
  const [runtimeDiagnosticsOpen, setRuntimeDiagnosticsOpen] = useState(false)
  const [chatColumnHidden, setChatColumnHidden] = useState(false)
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
  const showDevPreviewCard =
    route === 'chat' &&
    latestDevPreviewUrl !== null

  const hasStartedConversation =
    blocks.length > 0 ||
    busy ||
    liveAssistant.trim().length > 0 ||
    liveReasoning.trim().length > 0

  const stageCentered = !hasStartedConversation
  const activeWorkspaceRoot = useMemo(
    () => resolveActiveThreadWorkspace(activeThreadId, threads, workspaceRoot),
    [activeThreadId, threads, workspaceRoot]
  )
  const showOperationColumn =
    route === 'chat' && activeWorkspaceRoot.trim().length > 0 && !stageCentered
  const showRightSidebarToggle =
    route === 'chat' && activeWorkspaceRoot.trim().length > 0
  const showDefaultEditorPicker =
    route === 'chat' && activeWorkspaceRoot.trim().length > 0
  const showTopbarRightActions = showDefaultEditorPicker || showRightSidebarToggle
  const topbarRightPaddingClass = showTopbarRightActions
    ? showDefaultEditorPicker && showRightSidebarToggle
      ? 'pr-[7rem] sm:pr-[7.5rem]'
      : showDefaultEditorPicker
        ? 'pr-[5.25rem]'
        : 'pr-9 sm:pr-10'
    : ''
  const operationColumnActive = showOperationColumn && !rightSidebarOpen
  const rightPanelVisible = rightSidebarOpen && !rightSidebarCollapsed
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
    setRightSidebarOpen(true)
    setRightSidebarCollapsed(false)
    setRightSidebarTab('changes')
  }

  const openRightSidebar = useCallback((tab: RightSidebarTab): void => {
    setRightSidebarOpen(true)
    setRightSidebarCollapsed(false)
    setRightSidebarTab(tab)
  }, [])

  const openFileInEditor = useCallback(
    (path: string): void => {
      openRightSidebar('editor')
      void openEditorFile(path, activeWorkspaceRoot)
    },
    [activeWorkspaceRoot, openEditorFile, openRightSidebar]
  )

  const closeRightSidebar = useCallback((): void => {
    setRightSidebarOpen(false)
    setRightSidebarCollapsed(false)
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
  }, [rightSidebarCollapsed, rightSidebarOpen])

  const toggleRightSidebarMaximize = useCallback((): void => {
    const mainWidth = readMainRowWidth(
      shellRef,
      mainRowRef,
      !leftSidebarCollapsed,
      leftSidebarWidth
    )
    if (chatColumnHidden) {
      setRightSidebarWidth(resolveHalfRightWidth(mainWidth))
      setChatColumnHidden(false)
      return
    }
    setRightSidebarWidth(mainWidth)
    setChatColumnHidden(true)
  }, [chatColumnHidden, leftSidebarCollapsed, leftSidebarWidth])

  useEffect(() => {
    inputRef.current = input
  }, [input])

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
        !leftSidebarCollapsed,
        leftSidebarWidth
      )
      setRightSidebarWidth(resolveHalfRightWidth(mainWidth))
      setChatColumnHidden(false)
    }
  }, [leftSidebarCollapsed, leftSidebarWidth, rightSidebarCollapsed, rightSidebarOpen])

  useEffect(() => {
    const onPreview = (event: Event): void => {
      const detail = (event as CustomEvent<WorkspaceFilePreviewDetail>).detail
      if (!detail?.path) return
      openRightSidebar('editor')
      void openEditorFile(
        detail.path,
        detail.workspaceRoot ?? activeWorkspaceRoot,
        detail.line,
        detail.column
      )
    }

    window.addEventListener(WORKSPACE_FILE_PREVIEW_EVENT, onPreview)
    return () => window.removeEventListener(WORKSPACE_FILE_PREVIEW_EVENT, onPreview)
  }, [activeWorkspaceRoot, openEditorFile, openRightSidebar])

  useEffect(() => {
    const onOpenChanges = (): void => openRightSidebar('changes')
    window.addEventListener('deepseekgui:open-changes-panel', onOpenChanges)
    return () => window.removeEventListener('deepseekgui:open-changes-panel', onOpenChanges)
  }, [openRightSidebar])

  useEffect(() => {
    if (previewThreadId.current === activeThreadId) return
    previewThreadId.current = activeThreadId
    autoOpenedPreviewUrlRef.current = null
    if (rightSidebarOpen && rightSidebarTab === 'preview') {
      closeRightSidebar()
    }
  }, [activeThreadId, closeRightSidebar, rightSidebarOpen, rightSidebarTab])

  useEffect(() => {
    if (!latestDevPreviewUrl || route !== 'chat') return
    if (autoOpenedPreviewUrlRef.current === latestDevPreviewUrl) return
    autoOpenedPreviewUrlRef.current = latestDevPreviewUrl
    openRightSidebar('preview')
  }, [latestDevPreviewUrl, openRightSidebar, route])

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
      const target = e.target as HTMLElement | null
      const typing = Boolean(target?.closest('input, textarea, [contenteditable="true"]'))

      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'n') {
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

      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'b' && !typing) {
        e.preventDefault()
        setLeftSidebarCollapsed((current) => !current)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [createThread, setRoute])

  useEffect(() => {
    const sync = (): void => {
      const containerWidth = shellRef.current?.clientWidth ?? window.innerWidth
      const measuredMain = mainRowRef.current?.clientWidth ?? null
      const next = fitWorkbenchWidths(
        containerWidth,
        leftSidebarWidth,
        rightSidebarWidth,
        {
          leftPanelVisible: !leftSidebarCollapsed,
          rightPanelVisible
        },
        measuredMain
      )
      if (next.left !== leftSidebarWidth) setLeftSidebarWidth(next.left)
      if (rightPanelVisible && next.right !== rightSidebarWidth) {
        setRightSidebarWidth(next.right)
      }
      setChatColumnHidden(next.chatHidden)
    }
    sync()
    window.addEventListener('resize', sync)
    return () => window.removeEventListener('resize', sync)
  }, [leftSidebarCollapsed, leftSidebarWidth, rightSidebarWidth, rightPanelVisible])

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
    // Context-aware New Agent: when a real project is active the new agent
    // belongs to that project (inherit its workspace); otherwise it is a
    // temporary (Chats) thread. Reveal the Chats section so the new temporary
    // thread is visible even if it was collapsed.
    // Note: a temporary chat's workspace is `~/.deepseekgui/default_workspace`,
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

  const startNewChatInWorkspace = (workspaceRoot: string): void => {
    setRoute('chat')
    void createThread({ workspaceRoot })
  }

  const closeRightSidebarPanel = (): void => {
    closeRightSidebar()
  }

  const expandLeftSidebar = (): void => {
    setLeftSidebarCollapsed(false)
  }

  const sidebarWrapWidth = leftSidebarWidth

  const togglePreviewPanel = (): void => {
    if (rightSidebarOpen && rightSidebarTab === 'preview' && !rightSidebarCollapsed) {
      closeRightSidebar()
      return
    }
    openRightSidebar('preview')
  }

  const toggleTerminalPanel = (): void => {
    if (!activeWorkspaceRoot.trim()) return
    if (bottomTerminalOpen) {
      setBottomTerminalOpen(false)
      return
    }
    // Bottom terminal and the right-sidebar terminal tab share one global xterm
    // session store, so only one may mount at a time: hand the mount over by
    // steering the sidebar off its terminal tab before opening the bottom panel.
    if (terminalSidebarOpen) closeRightSidebar()
    setBottomTerminalOpen(true)
  }

  const openDevPreview = (): void => {
    if (latestDevPreviewUrl) {
      autoOpenedPreviewUrlRef.current = latestDevPreviewUrl
    }
    openRightSidebar('preview')
  }

  const beginLeftResize = (event: ReactPointerEvent<HTMLDivElement>): void => {
    if (leftSidebarCollapsed || event.button !== 0) return
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
      if (rightPanelVisible) {
        if (next.right !== rightSidebarWidth) setRightSidebarWidth(next.right)
        setChatColumnHidden(next.chatHidden)
      }
    }

    const onUp = (): void => {
      document.body.style.cursor = prevCursor
      document.body.style.userSelect = prevUserSelect
      wrapEl?.classList.remove('is-resizing')
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

    const onMove = (moveEvent: PointerEvent): void => {
      const containerWidth = shellRef.current?.clientWidth ?? window.innerWidth
      const measuredMain = mainRowRef.current?.clientWidth ?? null
      const delta = moveEvent.clientX - startX
      const next = fitWorkbenchWidths(
        containerWidth,
        startLeft,
        startRight - delta,
        {
          leftPanelVisible: !leftSidebarCollapsed,
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
    >
      {/* Chat route reopens the sidebar from the topbar button below (Synara
          SidebarTrigger in the content header); the floating droplet remains
          for routes without that header (plugins/automation/channels). */}
      {leftSidebarCollapsed && route !== 'chat' ? (
        <SidebarExpandDroplet onExpand={expandLeftSidebar} />
      ) : null}
      {/* Stays mounted while collapsed so the offcanvas slide can animate: the
          wrap's width shrinks to 0 while the fixed-width inner column slides
          left, both on the same 300ms curve (Synara sidebar gap + container). */}
      <div
        className="ds-workbench-sidebar-wrap relative min-h-0 shrink-0"
        data-collapsed={leftSidebarCollapsed ? '' : undefined}
        aria-hidden={leftSidebarCollapsed}
        inert={leftSidebarCollapsed || undefined}
        style={{ width: leftSidebarCollapsed ? 0 : sidebarWrapWidth }}
      >
        <div
          className="ds-workbench-sidebar-slide absolute inset-y-0 left-0"
          style={{
            width: sidebarWrapWidth,
            transform: leftSidebarCollapsed ? 'translateX(-100%)' : 'translateX(0)'
          }}
        >
          <Sidebar
            threads={threads}
            activeThreadId={activeThreadId}
            runtimeReady={runtimeConnection === 'ready'}
            onSelectThread={openThread}
            onOpenThreadTerminal={openThreadTerminal}
            onDeleteThread={deleteThread}
            onCompactThread={async (id) => {
              if (activeThreadId !== id) {
                setRoute('chat')
                await selectThread(id)
              }
              await compactActiveThread()
            }}
            onNewChat={startNewChat}
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
          route === 'plugins' || route === 'skills' || route === 'connectors' ? 'px-0' : ''
        }`}
      >
        {route === 'plugins' || route === 'skills' || route === 'connectors' ? (
          <Suspense fallback={<div className="h-full bg-transparent" />}>
            {route === 'skills' ? (
              <SkillsView />
            ) : route === 'connectors' ? (
              <ConnectorsView />
            ) : (
              <PluginsView />
            )}
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

        <div ref={mainRowRef} className="flex min-h-0 flex-1">
          <div className={`min-h-0 min-w-0 flex-1 flex-col ${chatColumnHidden ? 'hidden' : 'flex'}`}>
          <section className="ds-drag flex min-h-0 min-w-0 flex-1 flex-col">
            <header className="ds-workbench-topbar ds-surface-divider relative z-10 shrink-0 bg-transparent">
              <div className="ds-workbench-topbar__inner flex w-full min-w-0 items-center justify-between gap-2 py-0.5">
                {leftSidebarCollapsed ? (
                  <button
                    type="button"
                    onClick={expandLeftSidebar}
                    className="ds-sidebar-toggle-button ds-no-drag shrink-0"
                    aria-label={t('sidebarExpand')}
                    title={t('sidebarExpandShortcut')}
                  >
                    <PanelLeftOpen className="h-4 w-4" strokeWidth={1.85} />
                  </button>
                ) : null}
                <div className="min-w-0 flex-1 overflow-hidden">
                  <SessionHeader compact className="min-w-0" />
                </div>
                <div className={`flex shrink-0 items-center gap-1.5 ${topbarRightPaddingClass}`}>
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
                      open={rightSidebarOpen}
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
                <div className="ds-empty-stage flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
                  <div className="ds-empty-stage-frame flex min-h-0 min-w-0 flex-1 flex-col">
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
                        devPreviewCard={
                          showDevPreviewCard ? (
                            <DevPreviewLaunchCard
                              url={latestDevPreviewUrl}
                              onOpen={openDevPreview}
                            />
                          ) : null
                        }
                      />
                    </div>
                    <div className="ds-chat-stage ds-empty-stage-composer mt-auto shrink-0">
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
                        onInterrupt={() => void interrupt()}
                      />
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
                      devPreviewCard={
                        showDevPreviewCard ? (
                          <DevPreviewLaunchCard
                            url={latestDevPreviewUrl}
                            onOpen={openDevPreview}
                          />
                        ) : null
                      }
                    />
                    {showOperationColumn ? (
                      <div className="ds-dialogue-gutter shrink-0 pb-2 md:hidden">
                        <OperationContextDock
                          onOpenChanges={handleComposerOpenDiff}
                          onOpenEditor={() => openRightSidebar('editor')}
                          previewActive={rightSidebarOpen && rightSidebarTab === 'preview'}
                          terminalPanelOpen={bottomTerminalOpen}
                          terminalPanelEnabled={activeWorkspaceRoot.trim().length > 0}
                          previewEnabled={activeWorkspaceRoot.trim().length > 0}
                          onTogglePreview={togglePreviewPanel}
                          onToggleTerminalPanel={toggleTerminalPanel}
                        />
                      </div>
                    ) : null}
                    <div className="mx-auto flex w-full shrink-0 -mt-6 pb-0 pt-0">
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
                        onInterrupt={() => void interrupt()}
                      />
                    </div>
                  </div>
                  <aside className="ds-operation-rail ds-no-drag hidden h-full min-h-0 shrink-0 md:flex">
                    <div className="ds-operation-rail__scroll min-h-0 flex-1 overflow-y-auto pb-4 pl-0 pr-0 pt-[var(--ds-operation-stack-offset)]">
                      <OperationContextDock
                        onOpenChanges={handleComposerOpenDiff}
                        onOpenEditor={() => openRightSidebar('editor')}
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
                    devPreviewCard={
                      showDevPreviewCard ? (
                        <DevPreviewLaunchCard
                          url={latestDevPreviewUrl}
                          onOpen={openDevPreview}
                        />
                      ) : null
                    }
                  />
                  <div className="mx-auto flex w-full shrink-0 -mt-6 pb-0 pt-0">
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
                      onInterrupt={() => void interrupt()}
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
            devPreviewBlocks={devPreviewBlocks}
            latestDevPreviewUrl={latestDevPreviewUrl}
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

function DevPreviewLaunchCard({
  url,
  onOpen
}: {
  url: string
  onOpen: () => void
}): ReactElement {
  const { t } = useTranslation('common')
  return (
    <div className="flex min-h-[72px] w-full items-center gap-3 rounded-[12px] border border-ds-border-muted bg-ds-elevated/90 px-4 py-3 shadow-[0_12px_34px_rgba(0,0,0,0.07)] backdrop-blur-xl dark:border-white/[0.09] dark:bg-white/[0.045] dark:shadow-[0_18px_48px_rgba(0,0,0,0.18)]">
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-sky-400/20 bg-sky-500/10 text-sky-500 dark:border-sky-300/20 dark:bg-sky-300/10 dark:text-sky-300">
        <Globe2 className="h-5 w-5" strokeWidth={1.9} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="truncate text-[14.5px] font-semibold text-ds-ink">
          {t('devPreviewCardTitle')}
        </div>
        <div
          className="mt-1 flex min-w-0 items-center gap-1.5 text-[12.5px] text-ds-muted"
          title={url}
        >
          <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-400 shadow-[0_0_0_3px_rgba(52,211,153,0.12)]" />
          <span className="truncate">
            {t('devPreviewCardSubtitle')} · {formatDevPreviewUrlLabel(url)}
          </span>
        </div>
      </div>
      <button
        type="button"
        onClick={onOpen}
        className="inline-flex h-9 shrink-0 items-center justify-center rounded-full bg-accent px-4 text-[13px] font-semibold text-white shadow-[0_10px_24px_rgba(0,136,255,0.22)] transition hover:brightness-110"
        title={t('devPreviewCardOpen')}
      >
        {t('devPreviewCardOpen')}
      </button>
    </div>
  )
}
