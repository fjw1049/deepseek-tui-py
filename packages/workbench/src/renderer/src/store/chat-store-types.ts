import type {
  AgentProviderId,
  ChatBlock,
  NormalizedThread,
  RuntimeConnectionStatus,
  UserInputAnswer
} from '../agent/types'

export type QueuedUserMessage = {
  id: string
  text: string
  displayText?: string
  mode?: string
  model?: string
  modelLabel?: string
}

export type SendMessageOverrides = {
  queued?: QueuedUserMessage
  /** Shown in the timeline; `text` is still sent to the runtime. */
  displayText?: string
}

export type InitialSetupMode = 'required' | 'preview'
export type SettingsRouteSection =
  | 'general'
  | 'runtime'
  | 'memory'
  | 'permissions'
  | 'mcp'
  | 'skill'
  | 'hooks'
  | 'claw'

/** @deprecated Use `runtime`; kept for deep-link normalization. */
export type LegacySettingsRouteSection = SettingsRouteSection | 'agents'
export type AppRoute = 'chat' | 'settings' | 'plugins' | 'automation'
export type PluginHostRoute = 'chat'

export type ChatState = {
  route: AppRoute
  pluginHostRoute: PluginHostRoute
  settingsSection: SettingsRouteSection
  initialSetupOpen: boolean
  initialSetupMode: InitialSetupMode
  providerId: AgentProviderId
  workspaceRoot: string
  workspaceLabel: string
  runtimeConnection: RuntimeConnectionStatus
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
  composerModel: string
  composerPickList: string[]
  queuedMessages: QueuedUserMessage[]
  watchTurnCompletion: Record<string, boolean>
  unreadThreadIds: Record<string, boolean>
  scrollToBlockId: string | null
  setError: (message: string | null) => void
  setComposerModel: (modelId: string) => void
  loadComposerModels: () => Promise<void>
  setRoute: (r: AppRoute) => void
  openCode: () => Promise<void>
  openSettings: (section?: SettingsRouteSection) => void
  openPlugins: (host?: PluginHostRoute) => void
  openInitialSetup: (mode?: InitialSetupMode) => void
  closeInitialSetup: () => void
  boot: () => Promise<void>
  probeRuntime: (mode?: 'user' | 'background') => Promise<void>
  chooseWorkspace: (options?: { createThreadAfter?: boolean }) => Promise<string | null>
  clearWorkspace: () => Promise<void>
  deleteWorkspace: (workspacePath: string) => Promise<void>
  refreshThreads: () => Promise<void>
  createThread: (options?: { workspaceRoot?: string }) => Promise<void>
  selectThread: (id: string) => Promise<void>
  recoverActiveTurn: () => Promise<boolean>
  sendMessage: (text: string, mode?: string, overrides?: SendMessageOverrides) => Promise<boolean>
  drainQueuedMessages: () => Promise<void>
  removeQueuedMessage: (id: string) => void
  rewindAndResend: (userBlockId: string, newText: string) => Promise<void>
  interrupt: () => Promise<void>
  renameActiveThread: (title: string) => Promise<void>
  deleteThread: (threadId: string) => Promise<void>
  forkThread: (threadId: string) => Promise<void>
  resumeThread: (threadId: string) => Promise<void>
  compactActiveThread: () => Promise<void>
  importTuiSession: (input: { sessionId?: string; path?: string; title?: string }) => Promise<void>
  exportThreadToSession: (threadId: string) => Promise<{ path: string } | null>
  scrollToBlock: (blockId: string) => void
  clearScrollTarget: () => void
  resolveApproval: (blockId: string, decision: 'allow' | 'deny', remember?: boolean) => Promise<void>
  resolveElevation: (blockId: string, decision: 'allow' | 'deny') => Promise<void>
  resolveUserInput: (
    blockId: string,
    action: { kind: 'submit'; answers: UserInputAnswer[] } | { kind: 'cancel' }
  ) => Promise<void>
  selectInspectorItem: (id: string | null) => void
  applyI18nFromSettings: (locale: 'en' | 'zh') => Promise<void>
  reloadUiSettings: () => Promise<void>
}

export type ChatStoreSet = (
  partial: Partial<ChatState> | ((state: ChatState) => Partial<ChatState>)
) => void

export type ChatStoreGet = () => ChatState
