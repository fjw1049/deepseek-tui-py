import type { AppSettingsPatch, AppSettingsV1 } from './app-settings'
import type { EditorListResult, EditorOpenResult, OpenEditorPathOptions } from './editor'
import type { GitBranchesResult } from './git-branches'
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
export type PathOpenResult = { ok: boolean; message?: string }
export type SkillSaveResult = { ok: true; path: string } | { ok: false; message: string }
export type DeepseekConfigFileResult = { path: string; content: string; exists: boolean }
export type DeepseekConfigSaveResult = { ok: true; path: string }
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
    portOwner: {
      pid: number
      command: string
      parentPid: number | null
      parentCommand: string | null
    } | null
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

export type DsGuiApi = {
  platform: string
  getSettings: () => Promise<AppSettingsV1>
  setSettings: (partial: AppSettingsPatch) => Promise<AppSettingsV1>
  runtimeRequest: (path: string, method?: string, body?: string) => Promise<RuntimeRequestResult>
  fetchUpstreamModels: () => Promise<UpstreamModelsResult>
  deepseekSpawnIfNeeded: () => Promise<DeepseekSpawnResult>
  prepareDeepseekBinary: () => Promise<{ ok: true; path: string } | { ok: false; message: string }>
  pickWorkspaceDirectory: (defaultPath?: string) => Promise<WorkspacePickResult>
  listTuiSessions: () => Promise<ListTuiSessionsResult>
  pickTuiSessionFile: (defaultPath?: string) => Promise<TuiSessionPickResult>
  saveSkillFile: (rootPath: string, skillName: string, content: string) => Promise<SkillSaveResult>
  openSkillRoot: (rootPath: string) => Promise<PathOpenResult>
  getDeepseekConfigFile: () => Promise<DeepseekConfigFileResult>
  setDeepseekConfigFile: (content: string) => Promise<DeepseekConfigSaveResult>
  openDeepseekConfigDir: () => Promise<PathOpenResult>
  diagnoseDeepseekRuntime: () => Promise<DeepseekRuntimeDiagnosticsResult>
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
}
