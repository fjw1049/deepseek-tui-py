import type {
  AgentProviderId,
  ActivePluginMeta,
  ChatBlock,
  NormalizedThread,
  RuntimeConnectionStatus,
  TurnCompletePayload,
  UserInputAnswer
} from '../agent/types'
import type { ComposerModelMeta } from '../lib/composer-model-label'
import type { StartupPhasePayload } from '@shared/ds-gui-api'

export type QueuedUserMessage = {
  id: string
  text: string
  displayText?: string
  mode?: string
  model?: string
  modelLabel?: string
  hidden?: boolean
}

export type SendMessageOverrides = {
  queued?: QueuedUserMessage
  /** Shown in the timeline; `text` is still sent to the runtime. */
  displayText?: string
  /**
   * Skip the optimistic user bubble and ask the runtime not to persist a
   * user_message item (plugin mount/unmount-only control turns).
   */
  hidden?: boolean
}

export type SettingsRouteSection =
  | 'general'
  | 'appearance'
  | 'models'
  | 'permissions'
  | 'hooks'

/** @deprecated Use `models` or `general`; kept for deep-link normalization.
 * `mcp`/`skill` moved to the 应用拓展 连接器/技能 pages; old deep-links fall back to `general`. */
export type LegacySettingsRouteSection =
  | SettingsRouteSection
  | 'agents'
  | 'runtime'
  | 'claw'
  | 'mcp'
  | 'skill'
export type AppRoute =
  | 'chat'
  | 'settings'
  | 'plugins'
  | 'skills'
  | 'connectors'
  | 'automation'
  | 'channels'
export type PluginHostRoute = 'chat'
export type ThreadWarmupStatus = 'idle' | 'warming' | 'ready' | 'failed'
export type ThreadWarmupState = {
  threadId: string | null
  status: ThreadWarmupStatus
}

export type ChatState = {
  route: AppRoute
  pluginHostRoute: PluginHostRoute
  settingsSection: SettingsRouteSection
  initialSetupOpen: boolean
  providerId: AgentProviderId
  workspaceRoot: string
  workspaceLabel: string
  runtimeConnection: RuntimeConnectionStatus
  startupPhase: StartupPhasePayload | null
  activeThreadWarmup: ThreadWarmupState
  threads: NormalizedThread[]
  activeThreadId: string | null
  blocks: ChatBlock[]
  liveReasoning: string
  liveAssistant: string
  lastSeq: number
  busy: boolean
  error: string | null
  runtimeErrorDetail: string | null
  currentTurnId: string | null
  currentTurnUserId: string | null
  turnStartedAtByUserId: Record<string, number>
  turnDurationByUserId: Record<string, number>
  turnReasoningFirstAtByUserId: Record<string, number>
  turnReasoningLastAtByUserId: Record<string, number>
  inspectorSelectedId: string | null
  gitCommitSelectionKey: string | null
  gitCommitSelectedPaths: string[]
  composerModel: string
  composerPickList: string[]
  composerModelMeta: Record<string, ComposerModelMeta>
  composerReasoningEffort: string
  queuedMessages: QueuedUserMessage[]
  watchTurnCompletion: Record<string, boolean>
  unreadThreadIds: Record<string, boolean>
  pinnedThreadIds: string[]
  sidebarSearchQuery: string
  chatsCollapsed: boolean
  scrollToBlockId: string | null
  /** Session-level mounted plugin (drives the composer chip). null = none. */
  activePlugin: ActivePluginMeta | null
  usageRefreshKey: number
  setError: (message: string | null) => void
  setStartupPhase: (phase: StartupPhasePayload | null) => void
  setComposerModel: (modelId: string) => void
  setComposerReasoningEffort: (effort: string) => void
  loadComposerModels: () => Promise<void>
  setRoute: (r: AppRoute) => void
  setActivePlugin: (plugin: ActivePluginMeta | null) => void
  openCode: () => Promise<void>
  openSettings: (section?: SettingsRouteSection) => void
  openPlugins: (host?: PluginHostRoute) => void
  openSkills: () => void
  openConnectors: () => void
  closeInitialSetup: () => void
  boot: () => Promise<void>
  probeRuntime: (mode?: 'user' | 'background') => Promise<void>
  chooseWorkspace: (options?: { createThreadAfter?: boolean }) => Promise<string | null>
  clearWorkspace: () => Promise<void>
  deleteWorkspace: (workspacePath: string) => Promise<void>
  refreshThreads: () => Promise<void>
  createThread: (options?: { workspaceRoot?: string; chats?: boolean }) => Promise<void>
  selectThread: (id: string) => Promise<void>
  warmActiveThread: (threadId?: string) => Promise<void>
  recoverActiveTurn: () => Promise<boolean>
  sendMessage: (text: string, mode?: string, overrides?: SendMessageOverrides) => Promise<boolean>
  drainQueuedMessages: () => Promise<void>
  removeQueuedMessage: (id: string) => void
  rewindAndResend: (userBlockId: string, newText: string) => Promise<void>
  interrupt: () => Promise<void>
  renameActiveThread: (title: string) => Promise<void>
  renameThread: (threadId: string, title: string) => Promise<void>
  deleteThread: (threadId: string) => Promise<void>
  markThreadUnread: (threadId: string) => void
  togglePin: (threadId: string) => void
  setSidebarSearchQuery: (query: string) => void
  setChatsCollapsed: (collapsed: boolean) => void
  forkThread: (threadId: string, throughItemId?: string) => Promise<void>
  resumeThread: (threadId: string) => Promise<void>
  compactActiveThread: () => Promise<void>
  exportThreadToSession: (threadId: string) => Promise<{ path: string } | null>
  scrollToBlock: (blockId: string) => void
  clearScrollTarget: () => void
  resolveApproval: (blockId: string, decision: 'allow' | 'deny', remember?: boolean) => Promise<void>
  resolveEvolution: (blockId: string, decision: 'approve' | 'reject') => Promise<void>
  resolveElevation: (blockId: string, decision: 'allow' | 'deny') => Promise<void>
  resolveUserInput: (
    blockId: string,
    action: { kind: 'submit'; answers: UserInputAnswer[] } | { kind: 'cancel' }
  ) => Promise<void>
  selectInspectorItem: (id: string | null) => void
  syncGitCommitSelection: (allPaths: string[]) => void
  toggleGitCommitPath: (path: string, allPaths: string[]) => void
  setGitCommitSelectedPaths: (paths: string[]) => void
  applyI18nFromSettings: (locale: 'en' | 'zh') => Promise<void>
  reloadUiSettings: () => Promise<void>
}

export type ChatStoreSet = (
  partial: Partial<ChatState> | ((state: ChatState) => Partial<ChatState>)
) => void

export type ChatStoreGet = () => ChatState
