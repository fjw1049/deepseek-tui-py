import type { AppSettingsPatch, AppSettingsV1 } from './app-settings'
import type { EditorListResult, EditorOpenResult, OpenEditorPathOptions } from './editor'
import type { GitBranchesResult } from './git-branches'
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
  WorkspaceFileTarget
} from './workspace-file'

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

export type DsGuiApi = {
  platform: string
  getSettings: () => Promise<AppSettingsV1>
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
  getDeepseekPaths: () => Promise<{
    home: string
    configPath: string
    mcpPath: string
    hooksDir: string
    skillsDir: string
  }>
  openHooksDir: () => Promise<PathOpenResult>
  diagnoseDeepseekRuntime: () => Promise<DeepseekRuntimeDiagnosticsResult>
  getWorkspaceSuggestions: (workspaceRoot: string) => Promise<WorkspaceSuggestionsResult>
  getGitBranches: (workspaceRoot: string) => Promise<GitBranchesResult>
  switchGitBranch: (workspaceRoot: string, branch: string) => Promise<GitBranchesResult>
  createAndSwitchGitBranch: (workspaceRoot: string, branch: string) => Promise<GitBranchesResult>
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
