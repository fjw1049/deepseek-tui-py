import type { AppSettingsPatch, AppSettingsV1, EndpointProtocol } from './app-settings'
import type { EditorListResult, EditorOpenResult, OpenEditorPathOptions } from './editor'
import type { GitBranchesResult } from './git-branches'
import type { GitCommitMessageSuggestionResult, GitCommitResult } from './git-commit'
import type { GitLogResult } from './git-log'
import type { GitWorkingChangesResult } from './git-working-changes'
import type {
  PetFeaturedCacheResult,
  PetManifestFetchResult,
  PetSpritesheetResolveResult
} from './pet-manifest'
import type {
  TerminalCreateOptions,
  TerminalCreateResult,
  TerminalDataPayload,
  TerminalExitPayload,
  TerminalInputPayload,
  TerminalLifecyclePayload,
  TerminalResizePayload
} from './terminal-session'
import type {
  WorkspaceFileReadResult,
  WorkspaceFileResolveResult,
  WorkspaceFileTarget,
  WorkspaceFileWriteResult,
  WorkspaceFileWriteTarget,
  WorkspaceListDirectoryResult
} from './workspace-file'
import type { UsageQueryResult, UsageRange } from './usage-ledger'

export type RuntimeRequestResult = { ok: boolean; status: number; body: string }
export type WorkspacePickResult = { canceled: boolean; path: string | null }

export type WorkspacePickFilesResult =
  | { ok: true; paths: string[] }
  | { ok: false; message?: string; paths: [] }
export type TuiSessionPickResult = { canceled: boolean; path: string | null }
export type TuiSessionSummary = {
  sessionId: string
  path: string
  title: string
  model?: string
  workspace?: string
  messageCount: number
  modifiedAt: string
}
export type ListTuiSessionsResult = {
  dir: string
  sessions: TuiSessionSummary[]
}
export type PathOpenResult = { ok: boolean; message?: string; path?: string }
export type SkillSaveResult = { ok: true; path: string } | { ok: false; message: string }
export type DeepseekConfigFileResult = { path: string; content: string; exists: boolean }
export type DeepseekConfigSaveResult = { ok: true; path: string }
export type EndpointTestResult =
  | { ok: true; model: string; latencyMs: number; message: string }
  | { ok: false; model: string; latencyMs: number; message: string }

export type FeishuConfigV1 = {
  appId: string
  appSecret: string
  domain: string
  chatId: string
}

export type FeishuConfigFileResult = {
  path: string
  exists: boolean
  config: FeishuConfigV1
}
export type FeishuConfigSaveResult = { ok: true; path: string }

export type WecomConfigV1 = {
  webhookKey: string
}

export type WecomConfigFileResult = {
  path: string
  exists: boolean
  configured: boolean
  config: WecomConfigV1
}
export type WecomConfigSaveResult = { ok: true; path: string }

export type FeishuRegisterTarget = 'feishu' | 'lark'

export type FeishuRegisterEvent =
  | { type: 'qr'; url: string; expireIn: number }
  | { type: 'status'; status: string; interval?: number }

export type FeishuRegisterStartResult =
  | {
      ok: true
      result: {
        appId: string
        appSecret: string
        domain: FeishuRegisterTarget
        openId?: string
        tenantBrand?: 'feishu' | 'lark'
      }
    }
  | { ok: false; message: string }

export type EmailSecretStatusResult = {
  secureStorageAvailable: boolean
  passwordEnv: string
  hasStoredPassword: boolean
  hasEnvPassword: boolean
  passwordConfigured: boolean
}
export type DeepseekRuntimeDiagnosticIssue = {
  severity: 'info' | 'warning' | 'error'
  code: string
  title: string
  message: string
  path?: string
  line?: number
}
export type DeepseekRuntimeCatalogProbe = {
  ok: boolean
  status: number
  count: number | null
  warningCount?: number | null
  message?: string
}
export type DeepseekRuntimeDiagnosticsResult = {
  checkedAt: string
  settings: {
    port: number
    autoStart: boolean
    binaryPath: string
    baseUrl: string
    approvalPolicy: string
    sandboxMode: string
    hasApiKey: boolean
    hasRuntimeToken: boolean
  }
  binary: { ok: true; path: string } | { ok: false; message: string }
  config: {
    path: string
    exists: boolean
    content: string
    issues: DeepseekRuntimeDiagnosticIssue[]
  }
  runtime: {
    baseUrl: string
    configuredPort: number
    portOwner: {
      pid: number
      command: string
      parentPid: number | null
      parentCommand: string | null
    } | null
    alternateRuntimes: Array<{
      port: number
      pid: number
      command: string
      parentPid: number | null
      parentCommand: string | null
    }>
    health: { ok: boolean; status: number; body: string; message?: string }
    threadApi: { ok: boolean; status: number; body: string; message?: string } | null
    workspaceStatus: { ok: boolean; status: number; body: string; message?: string } | null
    skills: DeepseekRuntimeCatalogProbe | null
    tasks: DeepseekRuntimeCatalogProbe | null
    sessions: DeepseekRuntimeCatalogProbe | null
  }
  issues: DeepseekRuntimeDiagnosticIssue[]
}
export type TurnCompleteNotificationPayload = {
  threadId?: string
  title: string
  body: string
}
export type SystemNotificationResult =
  | { ok: true; shown: boolean; reason?: string }
  | { ok: false; message: string }
export type UpstreamModelsResult =
  | { ok: true; modelIds: string[] }
  | { ok: false; message: string }
export type DeepseekSpawnResult = {
  started: boolean
  healthy: boolean
  pid?: boolean
  error?: string
  message?: string
}
export type SseEventPayload = { streamId: string; data: unknown }
export type SseEndPayload = { streamId: string }
export type SseErrorPayload = { streamId: string; status?: number; message?: string }
export type StartupPhase =
  | 'app-ready'
  | 'settings'
  | 'renderer-loading'
  | 'runtime-check'
  | 'runtime-config-sync'
  | 'runtime-spawn'
  | 'runtime-health'
  | 'thread-api'
  | 'runtime-ready'
  | 'offline'

export type StartupPhasePayload = {
  phase: StartupPhase
  at: number
  detail?: string
}

export type RuntimeTokenRegenerateResult =
  | { ok: true; fingerprint: string; restarted: boolean; tokenPath?: string }
  | { ok: false; message: string }

export type RuntimeTokenFingerprintResult = {
  fingerprint: string
  tokenPath?: string
}

export type WorkspaceSuggestion = {
  id: string
  title: string
  desc: string
  prompt: string
  tone: 'blue' | 'emerald' | 'violet' | 'orange'
}
export type WorkspaceSuggestionsResult =
  | { ok: true; suggestions: WorkspaceSuggestion[] }
  | { ok: false; suggestions: null }

export type TrendingRepo = {
  rank: number
  name: string
  description: string
  stars: string
  gained: string
  topics: string[]
  isNew: boolean
  url: string
}
export type TrendingPeriod = 'daily' | 'weekly' | 'monthly'
export type TrendingResult =
  | { ok: true; repos: TrendingRepo[]; period: TrendingPeriod; cachedAt: number }
  | { ok: false; error: string }

export type { UsageQueryResult, UsageRange } from './usage-ledger'

export type DsGuiApi = {
  platform: string
  getSettings: () => Promise<AppSettingsV1>
  getStartupPhase: () => Promise<StartupPhasePayload | null>
  onStartupPhase: (handler: (payload: StartupPhasePayload) => void) => () => void
  setSettings: (partial: AppSettingsPatch) => Promise<AppSettingsV1>
  runtimeRequest: (path: string, method?: string, body?: string) => Promise<RuntimeRequestResult>
  fetchUpstreamModels: () => Promise<UpstreamModelsResult>
  deepseekSpawnIfNeeded: () => Promise<DeepseekSpawnResult>
  prepareDeepseekBinary: () => Promise<{ ok: true; path: string } | { ok: false; message: string }>
  pickWorkspaceDirectory: (defaultPath?: string) => Promise<WorkspacePickResult>
  pickWorkspaceFiles: (options: {
    workspaceRoot: string
    imagesOnly?: boolean
  }) => Promise<WorkspacePickFilesResult>
  listTuiSessions: () => Promise<ListTuiSessionsResult>
  pickTuiSessionFile: (defaultPath?: string) => Promise<TuiSessionPickResult>
  saveSkillFile: (rootPath: string, skillName: string, content: string) => Promise<SkillSaveResult>
  openSkillRoot: (rootPath: string) => Promise<PathOpenResult>
  listSkillsInRoot: (rootPath: string) => Promise<
    | { ok: true; skills: Array<{ id: string; name: string; path: string }> }
    | { ok: false; message?: string; skills: [] }
  >
  getDeepseekConfigFile: () => Promise<DeepseekConfigFileResult>
  setDeepseekConfigFile: (content: string) => Promise<DeepseekConfigSaveResult>
  openDeepseekConfigDir: () => Promise<PathOpenResult>
  getMcpConfigFile: () => Promise<DeepseekConfigFileResult>
  setMcpConfigFile: (content: string) => Promise<DeepseekConfigSaveResult>
  openMcpConfigDir: () => Promise<PathOpenResult>
  getFeishuConfig: () => Promise<FeishuConfigFileResult>
  setFeishuConfig: (config: FeishuConfigV1) => Promise<FeishuConfigSaveResult>
  openFeishuConfigDir: () => Promise<PathOpenResult>
  getWecomConfig: () => Promise<WecomConfigFileResult>
  setWecomConfig: (config: WecomConfigV1) => Promise<WecomConfigSaveResult>
  startFeishuRegister: (options?: { target?: FeishuRegisterTarget }) => Promise<FeishuRegisterStartResult>
  cancelFeishuRegister: () => Promise<{ ok: true }>
  onFeishuRegisterEvent: (handler: (payload: FeishuRegisterEvent) => void) => () => void
  getEmailSecretStatus: () => Promise<EmailSecretStatusResult>
  setEmailSecret: (password: string) => Promise<{ ok: true }>
  clearEmailSecret: () => Promise<{ ok: true }>
  getDeepseekPaths: () => Promise<{
    home: string
    configPath: string
    mcpPath: string
    hooksDir: string
    skillsDir: string
  }>
  openHooksDir: () => Promise<PathOpenResult>
  testEndpoint: (
    protocol: EndpointProtocol,
    baseUrl: string,
    apiKey: string,
    model: string
  ) => Promise<EndpointTestResult>
  diagnoseDeepseekRuntime: () => Promise<DeepseekRuntimeDiagnosticsResult>
  getWorkspaceSuggestions: (workspaceRoot: string) => Promise<WorkspaceSuggestionsResult>
  getTrendingRepos: (period: TrendingPeriod) => Promise<TrendingResult>
  queryUsage: (params?: { range?: UsageRange; locale?: string }) => Promise<UsageQueryResult>
  pruneUsageProvider: (providerId: string) => Promise<{ ok: true }>
  pruneUsageEndpointModel: (providerId: string, modelId: string) => Promise<{ ok: true }>
  getGitBranches: (workspaceRoot: string) => Promise<GitBranchesResult>
  getGitLog: (workspaceRoot: string) => Promise<GitLogResult>
  getGitWorkingChanges: (workspaceRoot: string) => Promise<GitWorkingChangesResult>
  switchGitBranch: (workspaceRoot: string, branch: string) => Promise<GitBranchesResult>
  createAndSwitchGitBranch: (workspaceRoot: string, branch: string) => Promise<GitBranchesResult>
  commitGitChanges: (
    workspaceRoot: string,
    message: string,
    paths?: string[]
  ) => Promise<GitCommitResult>
  suggestGitCommitMessage: (
    workspaceRoot: string,
    paths?: string[]
  ) => Promise<GitCommitMessageSuggestionResult>
  listEditors: () => Promise<EditorListResult>
  openEditorPath: (options: OpenEditorPathOptions) => Promise<EditorOpenResult>
  createTerminalSession: (options: TerminalCreateOptions) => Promise<TerminalCreateResult>
  writeTerminalSession: (payload: TerminalInputPayload) => Promise<boolean>
  resizeTerminalSession: (payload: TerminalResizePayload) => Promise<boolean>
  closeTerminalSession: (payload: TerminalLifecyclePayload) => Promise<boolean>
  onTerminalData: (handler: (payload: TerminalDataPayload) => void) => () => void
  onTerminalExit: (handler: (payload: TerminalExitPayload) => void) => () => void
  resolveWorkspaceFile: (options: WorkspaceFileTarget) => Promise<WorkspaceFileResolveResult>
  readWorkspaceFile: (options: WorkspaceFileTarget) => Promise<WorkspaceFileReadResult>
  writeWorkspaceFile: (options: WorkspaceFileWriteTarget) => Promise<WorkspaceFileWriteResult>
  listWorkspaceDirectory: (
    workspaceRoot: string,
    directoryPath?: string
  ) => Promise<WorkspaceListDirectoryResult>
  startSse: (threadId: string, sinceSeq: number, streamId?: string) => Promise<{ streamId: string }>
  stopSse: (streamId: string) => Promise<boolean>
  regenerateRuntimeToken: () => Promise<RuntimeTokenRegenerateResult>
  getRuntimeTokenFingerprint: () => Promise<RuntimeTokenFingerprintResult>
  onSseEvent: (handler: (payload: SseEventPayload) => void) => () => void
  onSseEnd: (handler: (payload: SseEndPayload) => void) => () => void
  onSseError: (handler: (payload: SseErrorPayload) => void) => () => void
  openExternal: (url: string) => Promise<void>
  showTurnCompleteNotification: (
    payload: TurnCompleteNotificationPayload
  ) => Promise<SystemNotificationResult>
  getAppVersion: () => Promise<string>
  logError: (category: string, message: string, detail?: unknown) => Promise<void>
  getLogPath: () => Promise<string>
  openLogDir: () => Promise<{ ok: boolean; message?: string }>
  fetchPetManifest: (force?: boolean) => Promise<PetManifestFetchResult>
  resolvePetSpritesheet: (slug?: string) => Promise<PetSpritesheetResolveResult>
  cacheFeaturedPets: (limit?: number) => Promise<PetFeaturedCacheResult>
}
