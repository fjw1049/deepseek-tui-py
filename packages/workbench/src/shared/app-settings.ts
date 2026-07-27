import {
  mergeAppearanceSettings,
  normalizeAppearanceSettings,
  type AppearancePatchV1,
  type AppearanceSettingsV1
} from './appearance'
import {
  CUSTOM_MODEL_CONTEXT_WINDOW_DEFAULT,
  normalizeCustomModelContextWindow
} from './app-settings-context-window'
import {
  BUILTIN_LLM_PROVIDER_IDS,
  BUILTIN_LLM_PROVIDERS,
  DEFAULT_LLM_PROVIDER_ID,
  defaultLlmProviders,
  isBuiltinLlmProviderId,
  migrateEnabledModelsToModels,
  normalizeLlmProviderModels,
  type BuiltinLlmProviderId,
  type LlmProviderConfigV1,
  type LlmProviderModelV1
} from './llm-providers'
import {
  defaultShortcutsSettings,
  mergeShortcutsSettings,
  normalizeShortcutsSettings,
  type ShortcutsPatchV1,
  type ShortcutsSettingsV1
} from './shortcuts'

export type { BuiltinLlmProviderId, LlmProviderConfigV1, LlmProviderModelV1 }
export {
  BUILTIN_LLM_PROVIDER_IDS,
  BUILTIN_LLM_PROVIDERS,
  DEFAULT_LLM_PROVIDER_ID,
  defaultLlmProviders,
  enabledLlmModelIds,
  isBuiltinLlmProviderId,
  providerHasApiKey,
  resolveProviderDefaultModel
} from './llm-providers'
export {
  CUSTOM_MODEL_CONTEXT_WINDOW_DEFAULT,
  CUSTOM_MODEL_CONTEXT_WINDOW_MAX,
  CUSTOM_MODEL_CONTEXT_WINDOW_MIN,
  normalizeCustomModelContextWindow
} from './app-settings-context-window'

export const GUI_UPDATE_CHANNELS = ['frontier', 'stable'] as const
export type GuiUpdateChannel = (typeof GUI_UPDATE_CHANNELS)[number]
export const DEFAULT_GUI_UPDATE_CHANNEL: GuiUpdateChannel = 'frontier'

function normalizeGuiUpdateChannel(value: unknown): GuiUpdateChannel {
  return value === 'stable' || value === 'frontier' ? value : DEFAULT_GUI_UPDATE_CHANNEL
}

export type ApprovalPolicy = 'on-request' | 'untrusted' | 'never' | 'auto' | 'suggest'
export type SandboxMode = 'read-only' | 'workspace-write' | 'danger-full-access' | 'external-sandbox'

/** Derive filesystem sandbox from the three product approval tiers (1A). */
export function sandboxModeForApprovalPolicy(policy: ApprovalPolicy): SandboxMode {
  return policy === 'auto' ? 'danger-full-access' : 'workspace-write'
}
export type UiFontScale = 'small' | 'medium' | 'large'
export type UiFontFamily = 'inter-noto' | 'system-native'
export type ClawRunMode = 'agent' | 'plan'
export type ClawImProvider = 'feishu'
export type ClawScheduleKind = 'manual' | 'interval' | 'daily' | 'at'
export type ClawTaskStatus = 'idle' | 'running' | 'success' | 'error'
export type ClawModel = 'auto' | 'deepseek-v4-pro' | 'deepseek-v4-flash'
export type MemoryMode = 'manual' | 'hybrid' | 'auto'
export type MemoryFtsTokenizer = 'auto' | 'simple' | 'jieba'
export type MemoryEmbeddingProvider = 'none' | 'openai'

export const DEFAULT_DEEPSEEK_BASE_URL = 'https://api.deepseek.com/beta'
export const DEFAULT_CLAW_MODEL = 'auto'
export const CLAW_MODEL_IDS = ['auto', 'deepseek-v4-pro', 'deepseek-v4-flash'] as const

export type DeepseekSettingsV1 = {
  binaryPath: string
  port: number
  autoStart: boolean
  apiKey: string
  baseUrl: string
  runtimeToken: string
  extraCorsOrigins: string[]
  /** Forwarded as `--approval-policy` to `deepseek serve`. */
  approvalPolicy: ApprovalPolicy
  /** Forwarded as `--sandbox-mode` to `deepseek serve`. */
  sandboxMode: SandboxMode
}

export type EndpointProtocol = 'openai' | 'anthropic'

export type CustomEndpointModelV1 = {
  /** Wire model identifier sent to the provider. */
  id: string
  /** Optional friendly label shown beside the wire identifier. */
  label?: string
  enabled: boolean
  /** Context window in tokens (default 500K, max 1M). Synced to config.toml. */
  contextWindow: number
  testStatus: 'untested' | 'passed' | 'failed'
  toolCalling?: boolean
  lastTestedAt?: string
}

export type CustomEndpointV1 = {
  /** Stable routing id; unlike name this must not change after creation. */
  id: string
  /** User-chosen name (e.g. "Qingyun", "My Local LLM"). */
  name: string
  protocol: EndpointProtocol
  baseUrl: string
  apiKey: string
  enabled: boolean
  models: CustomEndpointModelV1[]
}

export type LogConfigV1 = {
  enabled: boolean
  retentionDays: number
}

export type NotificationConfigV1 = {
  turnComplete: boolean
}

export const DEFAULT_ASR_MODEL = 'glm-asr-2512'
export const DEFAULT_ASR_BASE_URL = 'https://open.bigmodel.cn/api/paas/v4'
export const BUILTIN_ASR_PROVIDER_ID = 'zhipu-asr'

export type AsrSettingsV1 = {
  apiKey: string
  model: string
  baseUrl: string
}

export type AsrProviderModelV1 = {
  id: string
  enabled: boolean
}

export type AsrProviderV1 = {
  id: string
  name: string
  baseUrl: string
  apiKey: string
  models: AsrProviderModelV1[]
  /** Built-in vendors cannot be deleted from Settings. */
  builtin?: boolean
}

export type ClawSkillSettingsV1 = {
  defaultNames: string[]
  extraDirs: string[]
  promptPrefix: string
}

export type ClawImSettingsV1 = {
  enabled: boolean
  provider: ClawImProvider
  port: number
  path: string
  secret: string
  /** Default Feishu open_id / chat_id for scheduled task delivery (mode=feishu). */
  feishuReceiveId: string
  workspaceRoot: string
  model: string
  mode: ClawRunMode
  responseTimeoutMs: number
}

export type ClawTaskScheduleV1 = {
  kind: ClawScheduleKind
  everyMinutes: number
  timeOfDay: string
  atTime: string
}

export type ClawTaskV1 = {
  id: string
  title: string
  enabled: boolean
  prompt: string
  workspaceRoot: string
  model: string
  mode: ClawRunMode
  schedule: ClawTaskScheduleV1
  createdAt: string
  updatedAt: string
  lastRunAt: string
  nextRunAt: string
  lastStatus: ClawTaskStatus
  lastMessage: string
  lastThreadId: string
}

export type ClawImAgentProfileV1 = {
  name: string
  description: string
  identity: string
  personality: string
  userContext: string
  replyRules: string
}

export type ClawImPlatformCredentialV1 = {
  kind: 'feishu'
  appId: string
  appSecret: string
  domain: string
  createdAt: string
}

export type ClawImRemoteSessionV1 = {
  chatId: string
  messageId: string
  threadId: string
  senderId: string
  senderName: string
  updatedAt: string
}

export type ClawImConversationV1 = {
  id: string
  chatId: string
  remoteThreadId: string
  latestMessageId: string
  senderId: string
  senderName: string
  localThreadId: string
  workspaceRoot: string
  createdAt: string
  updatedAt: string
}

export type ClawImChannelV1 = {
  id: string
  provider: ClawImProvider
  label: string
  enabled: boolean
  model: ClawModel
  threadId: string
  workspaceRoot: string
  agentProfile: ClawImAgentProfileV1
  platformCredential?: ClawImPlatformCredentialV1
  remoteSession?: ClawImRemoteSessionV1
  conversations: ClawImConversationV1[]
  createdAt: string
  updatedAt: string
}

export type ClawSettingsV1 = {
  enabled: boolean
  skills: ClawSkillSettingsV1
  im: ClawImSettingsV1
  channels: ClawImChannelV1[]
  tasks: ClawTaskV1[]
}

export type ClawSettingsPatchV1 = Partial<Omit<ClawSettingsV1, 'skills' | 'im' | 'channels' | 'tasks'>> & {
  skills?: Partial<ClawSkillSettingsV1>
  im?: Partial<ClawImSettingsV1>
  channels?: Array<Partial<ClawImChannelV1>>
  tasks?: Array<Partial<ClawTaskV1>>
}

export type ClawRunResult =
  | { ok: true; threadId: string; turnId?: string; text?: string; message?: string }
  | { ok: false; message: string }

export type ClawRuntimeStatus = {
  imServerRunning: boolean
  imUrl: string
  runningTaskIds: string[]
}

export type GuiUpdateConfigV1 = {
  channel: GuiUpdateChannel
}

export type WorkbenchSkillsConfigV1 = {
  /** Extra skill scan directories (migrated from legacy ``claw.skills.extraDirs``). */
  extraDirs: string[]
}

export type MemorySmartSettingsV1 = {
  enabled: boolean
  dataDir: string
  recallEnabled: boolean
  captureEnabled: boolean
  recallTimeoutMs: number
  recallScoreThreshold: number
  recallLimit: number
  captureMinUserChars: number
  l1EveryN: number
  l1IdleTimeoutSeconds: number
  l1ConfidenceMin: number
  l1MaxPerSession: number
  l1DecayHalfLifeDays: number
  hybridSearch: boolean
  ftsTokenizer: MemoryFtsTokenizer
  embeddingProvider: MemoryEmbeddingProvider
  embeddingModel: string
  embeddingBaseUrl: string
  embeddingApiKey: string
  embeddingDimensions: number | null
  embeddingDedupThreshold: number
  embeddingBackfillOnStart: boolean
}

export type MemorySettingsV1 = {
  enabled: boolean
  mode: MemoryMode
  smart: MemorySmartSettingsV1
}

export type MemorySettingsPatchV1 = Partial<Omit<MemorySettingsV1, 'smart'>> & {
  smart?: Partial<MemorySmartSettingsV1>
}

export type AppSettingsV1 = {
  version: 1
  locale: 'en' | 'zh'
  theme: 'system' | 'light' | 'dark'
  uiFontScale: UiFontScale
  uiFontFamily: UiFontFamily
  agentProvider: 'deepseek-runtime'
  deepseek: DeepseekSettingsV1
  /** Active vendor for `provider = …` in config.toml. Defaults to deepseek. */
  defaultLlmProviderId: BuiltinLlmProviderId
  /** Per-vendor API keys + models (built-in catalogue only). */
  llmProviders: Record<BuiltinLlmProviderId, LlmProviderConfigV1>
  customEndpoints: CustomEndpointV1[]
  /** Speech vendors (builtin Zhipu + user-added). Active one syncs to `[asr]`. */
  asrProviders: AsrProviderV1[]
  workspaceRoot: string
  log: LogConfigV1
  notifications: NotificationConfigV1
  skills: WorkbenchSkillsConfigV1
  memory: MemorySettingsV1
  claw: ClawSettingsV1
  guiUpdate: GuiUpdateConfigV1
  appearance: AppearanceSettingsV1
  shortcuts: ShortcutsSettingsV1
}

export type AppSettingsPatch = Partial<
  Omit<
    AppSettingsV1,
    | 'deepseek'
    | 'log'
    | 'notifications'
    | 'skills'
    | 'claw'
    | 'guiUpdate'
    | 'customEndpoints'
    | 'asrProviders'
    | 'llmProviders'
    | 'appearance'
    | 'shortcuts'
  >
> & {
  deepseek?: Partial<DeepseekSettingsV1>
  log?: Partial<LogConfigV1>
  notifications?: Partial<NotificationConfigV1>
  skills?: Partial<WorkbenchSkillsConfigV1>
  memory?: MemorySettingsPatchV1
  claw?: ClawSettingsPatchV1
  guiUpdate?: Partial<GuiUpdateConfigV1>
  customEndpoints?: CustomEndpointV1[]
  asrProviders?: AsrProviderV1[]
  llmProviders?: Partial<Record<BuiltinLlmProviderId, Partial<LlmProviderConfigV1>>>
  appearance?: AppearancePatchV1
  shortcuts?: ShortcutsPatchV1
}

export const CLAW_CURRENT_USER_REQUEST_HEADING = '[Current user request]'
export const CLAW_MANAGED_INSTRUCTIONS_HEADING = '[Claw managed instructions]'
export const CLAW_IM_AGENT_INSTRUCTIONS_HEADING = '[Claw IM agent instructions]'
export const CLAW_FEISHU_INBOUND_MESSAGE_HEADING = '[Feishu / Lark inbound message]'
export const AUTOMATION_COMPOSER_HEADING = '[Scheduled automation request]'
const CLAW_SCHEDULE_TOOL_HINT =
  'When the user asks to create, list, or delete scheduled automations or reminders, use the cron tools (`cron_create`, `cron_list`, `cron_delete`) instead of only describing steps. To change an existing job, delete it with `cron_delete` and recreate it with `cron_create` (deleting wipes its run history).'

export type AutomationComposerContext = {
  feishuChatId?: string
  mailTo?: string
  workspaceRoot?: string
  /** IANA timezone for user-facing schedule confirmations. */
  userTimezone?: string
}

export function buildAutomationComposerPrompt(
  userText: string,
  context: AutomationComposerContext = {}
): string {
  const trimmed = userText.trim()
  const feishuTo = context.feishuChatId?.trim() ?? ''
  const mailTo = context.mailTo?.trim() ?? ''
  const userTimezone = context.userTimezone?.trim() || 'Asia/Shanghai'
  const hints: string[] = [
    'The user wants a scheduled or delayed automation. Follow this playbook:',
    'Do NOT call tool_search_tool_regex, tool_search_tool_bm25, or any other discovery tools — tool names are listed below.',
    'Only use these tools for this request: cron_create (and cron_list/cron_delete if the user asks to manage existing jobs). To change an existing job, delete it with cron_delete and recreate it (deleting wipes its run history).',
    '1. Relative times ("in 2 minutes", "tomorrow morning") resolve against the `today: YYYY-MM-DD` date injected in the system prompt; call `exec_shell date` first when you need the exact current time.',
    '2. Recurring jobs: set `rrule` (FREQ=HOURLY;INTERVAL=N or FREQ=WEEKLY;BYDAY=MO;BYHOUR=9;BYMINUTE=30).',
    '3. One-shot or delayed runs: set `next_run_at` to the computed fire time (ISO8601 UTC) and use a far-future placeholder rrule such as FREQ=HOURLY;INTERVAL=8760.',
    '4. Call `cron_create` with name, prompt (the task to run), rrule, optional next_run_at/cwds, and delivery when the user wants results sent. Set run_now=true if the user also wants it to run immediately.',
    `5. Confirm the automation id, schedule, and delivery target in plain language. State the run time in ${userTimezone} local time — never guess or use UTC-only.`
  ]
  hints.push(
    `User timezone: ${userTimezone}. If you called exec_shell date, re-check the time if more than 30 seconds pass before cron_create.`
  )
  const wantsFeishu = /飞书|feishu|lark/i.test(trimmed)
  const wantsEmail = /邮箱|邮件|email|mail/i.test(trimmed)
  if (wantsFeishu || feishuTo) {
    if (feishuTo) {
      hints.push(
        'Feishu delivery is required. Do NOT ask the user for open_chat_id — use this configured target.',
        'You MUST pass delivery exactly as:',
        `{"mode":"feishu","to":"${feishuTo}","best_effort":true}`
      )
    } else {
      hints.push(
        'The user asked for Feishu delivery but no default chat_id is configured. Ask for the Feishu open_chat_id before calling cron_create.'
      )
    }
  }
  if (wantsEmail || mailTo) {
    if (mailTo) {
      hints.push(
        'Email delivery: pass delivery as:',
        `{"mode":"email","to":"${mailTo}","best_effort":true}`
      )
    } else if (!wantsFeishu) {
      hints.push(
        'The user asked for email delivery but no default mail_to is configured. Ask for the recipient address before calling cron_create.'
      )
    }
  }
  if (context.workspaceRoot?.trim()) {
    hints.push(`Workspace cwd for the task: ${context.workspaceRoot.trim()}`)
  }
  return [
    AUTOMATION_COMPOSER_HEADING,
    '',
    hints.join('\n'),
    '',
    '---',
    CLAW_CURRENT_USER_REQUEST_HEADING,
    trimmed
  ].join('\n')
}

export function defaultClawImAgentProfile(): ClawImAgentProfileV1 {
  return {
    name: '',
    description: '',
    identity: '',
    personality: '',
    userContext: '',
    replyRules: ''
  }
}

export function normalizeClawImAgentProfile(input: unknown): ClawImAgentProfileV1 {
  const raw = typeof input === 'object' && input !== null && !Array.isArray(input)
    ? input as Partial<ClawImAgentProfileV1>
    : {}
  return {
    name: typeof raw.name === 'string' ? raw.name.trim() : '',
    description: typeof raw.description === 'string' ? raw.description.trim() : '',
    identity: typeof raw.identity === 'string' ? raw.identity : '',
    personality: typeof raw.personality === 'string' ? raw.personality : '',
    userContext: typeof raw.userContext === 'string' ? raw.userContext : '',
    replyRules: typeof raw.replyRules === 'string' ? raw.replyRules : ''
  }
}

export function normalizeClawImPlatformCredential(input: unknown): ClawImPlatformCredentialV1 | undefined {
  const raw = typeof input === 'object' && input !== null && !Array.isArray(input)
    ? input as Partial<ClawImPlatformCredentialV1>
    : {}
  if (raw.kind !== 'feishu') return undefined
  const appId = typeof raw.appId === 'string' ? raw.appId.trim() : ''
  const appSecret = typeof raw.appSecret === 'string' ? raw.appSecret.trim() : ''
  if (!appId || !appSecret) return undefined
  return {
    kind: raw.kind,
    appId,
    appSecret,
    domain: typeof raw.domain === 'string' && raw.domain.trim() ? raw.domain.trim() : raw.kind,
    createdAt: typeof raw.createdAt === 'string' && raw.createdAt ? raw.createdAt : new Date().toISOString()
  }
}

export function normalizeClawImRemoteSession(input: unknown): ClawImRemoteSessionV1 | undefined {
  const raw = typeof input === 'object' && input !== null && !Array.isArray(input)
    ? input as Partial<ClawImRemoteSessionV1>
    : {}
  const chatId = typeof raw.chatId === 'string' ? raw.chatId.trim() : ''
  const messageId = typeof raw.messageId === 'string' ? raw.messageId.trim() : ''
  if (!chatId || !messageId) return undefined
  return {
    chatId,
    messageId,
    threadId: typeof raw.threadId === 'string' ? raw.threadId.trim() : '',
    senderId: typeof raw.senderId === 'string' ? raw.senderId.trim() : '',
    senderName: typeof raw.senderName === 'string' ? raw.senderName.trim() : '',
    updatedAt: typeof raw.updatedAt === 'string' && raw.updatedAt ? raw.updatedAt : new Date().toISOString()
  }
}

export function normalizeClawImConversation(input: unknown): ClawImConversationV1 | undefined {
  const raw = typeof input === 'object' && input !== null && !Array.isArray(input)
    ? input as Partial<ClawImConversationV1>
    : {}
  const id = typeof raw.id === 'string' ? raw.id.trim() : ''
  const chatId = typeof raw.chatId === 'string' ? raw.chatId.trim() : ''
  const latestMessageId = typeof raw.latestMessageId === 'string' ? raw.latestMessageId.trim() : ''
  const localThreadId = typeof raw.localThreadId === 'string' ? raw.localThreadId.trim() : ''
  if (!id || !chatId || !latestMessageId || !localThreadId) return undefined
  return {
    id,
    chatId,
    remoteThreadId: typeof raw.remoteThreadId === 'string' ? raw.remoteThreadId.trim() : '',
    latestMessageId,
    senderId: typeof raw.senderId === 'string' ? raw.senderId.trim() : '',
    senderName: typeof raw.senderName === 'string' ? raw.senderName.trim() : '',
    localThreadId,
    workspaceRoot: typeof raw.workspaceRoot === 'string' ? raw.workspaceRoot.trim() : '',
    createdAt: typeof raw.createdAt === 'string' && raw.createdAt ? raw.createdAt : new Date().toISOString(),
    updatedAt: typeof raw.updatedAt === 'string' && raw.updatedAt ? raw.updatedAt : new Date().toISOString()
  }
}

export function hasClawImAgentProfile(profile: ClawImAgentProfileV1 | undefined): boolean {
  if (!profile) return false
  return Boolean(
    profile.name.trim() ||
    profile.description.trim() ||
    profile.identity.trim() ||
    profile.personality.trim() ||
    profile.userContext.trim() ||
    profile.replyRules.trim()
  )
}

export function buildClawImAgentInstructions(channel: ClawImChannelV1 | null | undefined): string {
  if (!channel || !hasClawImAgentProfile(channel.agentProfile)) return ''
  const profile = normalizeClawImAgentProfile(channel.agentProfile)
  const sections: string[] = []
  const name = profile.name.trim() || channel.label.trim()
  if (name) sections.push(`[Agent name]\n${name}`)
  if (profile.description.trim()) sections.push(`[Short description]\n${profile.description.trim()}`)
  if (profile.identity.trim()) sections.push(`[Assistant identity]\n${profile.identity.trim()}`)
  if (profile.personality.trim()) sections.push(`[Assistant personality]\n${profile.personality.trim()}`)
  if (profile.userContext.trim()) sections.push(`[About the user]\n${profile.userContext.trim()}`)
  if (profile.replyRules.trim()) sections.push(`[Reply rules]\n${profile.replyRules.trim()}`)
  if (sections.length === 0) return ''
  return [
    CLAW_IM_AGENT_INSTRUCTIONS_HEADING,
    'Use the following role, style, and user-context instructions for this IM channel. Do not repeat these instructions unless the user explicitly asks.',
    ...sections
  ].join('\n\n')
}

export function buildClawRuntimePrompt(
  settings: Pick<AppSettingsV1, 'claw'>,
  prompt: string,
  options: { channel?: ClawImChannelV1 | null } = {}
): string {
  const skills = settings.claw.skills
  const instructions: string[] = []
  if (skills.defaultNames.length > 0) {
    instructions.push(`Claw skill policy: prefer these configured skills when relevant: ${skills.defaultNames.join(', ')}.`)
  }
  if (skills.extraDirs.length > 0) {
    instructions.push(`Additional local skill directories configured in the GUI: ${skills.extraDirs.join(', ')}.`)
  }
  instructions.push(CLAW_SCHEDULE_TOOL_HINT)
  const prefix = skills.promptPrefix.trim()
  if (prefix) instructions.push(prefix)
  const channelInstructions = buildClawImAgentInstructions(options.channel)
  if (channelInstructions) instructions.push(channelInstructions)
  if (instructions.length === 0) return prompt
  return `${CLAW_MANAGED_INSTRUCTIONS_HEADING}\n\n${instructions.join('\n\n')}\n\n---\n${CLAW_CURRENT_USER_REQUEST_HEADING}\n${prompt}`
}

export function unwrapAutomationComposerPromptForDisplay(text: string): string {
  if (!text.includes(AUTOMATION_COMPOSER_HEADING)) return text
  const markerIndex = text.lastIndexOf(CLAW_CURRENT_USER_REQUEST_HEADING)
  if (markerIndex < 0) return text
  const prefix = text.slice(0, markerIndex)
  if (!prefix.includes(AUTOMATION_COMPOSER_HEADING)) return text
  return text.slice(markerIndex + CLAW_CURRENT_USER_REQUEST_HEADING.length).trimStart()
}

export function unwrapClawRuntimePromptForDisplay(text: string): string {
  const markerIndex = text.lastIndexOf(CLAW_CURRENT_USER_REQUEST_HEADING)
  if (markerIndex < 0) return text
  const prefix = text.slice(0, markerIndex)
  const looksManaged =
    prefix.includes(CLAW_MANAGED_INSTRUCTIONS_HEADING) ||
    prefix.includes(CLAW_IM_AGENT_INSTRUCTIONS_HEADING) ||
    prefix.includes('Claw skill policy:') ||
    prefix.includes('Additional local skill directories configured in the GUI:')
  if (!looksManaged) return text
  return text.slice(markerIndex + CLAW_CURRENT_USER_REQUEST_HEADING.length).trimStart()
}

export function unwrapClawUserPromptForDisplay(text: string): string {
  const unwrapped = unwrapAutomationComposerPromptForDisplay(
    unwrapClawRuntimePromptForDisplay(text)
  )
  if (!unwrapped.startsWith(CLAW_FEISHU_INBOUND_MESSAGE_HEADING)) return unwrapped
  const splitIndex = unwrapped.indexOf('\n\n')
  if (splitIndex < 0) return unwrapped
  const message = unwrapped.slice(splitIndex + 2).trim()
  return message || unwrapped
}

export function normalizeDeepseekBaseUrl(baseUrl: string | null | undefined): string {
  const trimmed = typeof baseUrl === 'string' ? baseUrl.trim() : ''
  return trimmed || DEFAULT_DEEPSEEK_BASE_URL
}

function compactStrings(values: unknown): string[] {
  if (!Array.isArray(values)) return []
  const out: string[] = []
  const seen = new Set<string>()
  for (const value of values) {
    if (typeof value !== 'string') continue
    const trimmed = value.trim()
    if (!trimmed || seen.has(trimmed)) continue
    seen.add(trimmed)
    out.push(trimmed)
  }
  return out
}

function normalizeBoolean(value: unknown, fallback: boolean): boolean {
  return typeof value === 'boolean' ? value : fallback
}

function normalizeNumber(value: unknown, fallback: number, min: number, max: number): number {
  const parsed = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(parsed)) return fallback
  return Math.min(max, Math.max(min, parsed))
}

function normalizePositiveInteger(value: unknown, fallback: number, min: number, max: number): number {
  const parsed = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(parsed)) return fallback
  return Math.min(max, Math.max(min, Math.floor(parsed)))
}

function normalizeRunMode(value: unknown): ClawRunMode {
  return value === 'plan' ? 'plan' : 'agent'
}

function normalizeImProvider(value: unknown): ClawImProvider {
  void value
  return 'feishu'
}

export function normalizeClawModel(value: unknown): ClawModel {
  return value === 'deepseek-v4-pro' || value === 'deepseek-v4-flash' ? value : 'auto'
}

function normalizeScheduleKind(value: unknown): ClawScheduleKind {
  if (value === 'interval' || value === 'daily' || value === 'at') return value
  return 'manual'
}

function normalizeTimeOfDay(value: unknown): string {
  const raw = typeof value === 'string' ? value.trim() : ''
  return /^(?:[01]\d|2[0-3]):[0-5]\d$/.test(raw) ? raw : '09:00'
}

function normalizeAtTime(value: unknown): string {
  const raw = typeof value === 'string' ? value.trim() : ''
  if (!raw) return ''
  const parsed = new Date(raw)
  return Number.isFinite(parsed.getTime()) ? parsed.toISOString() : ''
}

function normalizePathSegment(value: unknown): string {
  const raw = typeof value === 'string' ? value.trim() : ''
  if (!raw) return '/claw/im'
  return raw.startsWith('/') ? raw : `/${raw}`
}

function normalizeStatus(value: unknown): ClawTaskStatus {
  if (value === 'running' || value === 'success' || value === 'error') return value
  return 'idle'
}

function normalizeMemoryMode(value: unknown): MemoryMode {
  if (value === 'manual' || value === 'auto') return value
  return 'hybrid'
}

function normalizeFtsTokenizer(value: unknown): MemoryFtsTokenizer {
  if (value === 'simple' || value === 'jieba') return value
  return 'auto'
}

function normalizeEmbeddingProvider(value: unknown): MemoryEmbeddingProvider {
  return value === 'openai' ? 'openai' : 'none'
}

export function defaultMemorySettings(): MemorySettingsV1 {
  return {
    enabled: false,
    mode: 'hybrid',
    smart: {
      enabled: false,
      dataDir: '',
      recallEnabled: true,
      captureEnabled: true,
      recallTimeoutMs: 5000,
      recallScoreThreshold: 0.3,
      recallLimit: 8,
      captureMinUserChars: 20,
      l1EveryN: 5,
      l1IdleTimeoutSeconds: 600,
      l1ConfidenceMin: 0.6,
      l1MaxPerSession: 20,
      l1DecayHalfLifeDays: 180,
      hybridSearch: true,
      ftsTokenizer: 'auto',
      embeddingProvider: 'none',
      embeddingModel: 'text-embedding-3-large',
      embeddingBaseUrl: '',
      embeddingApiKey: '',
      embeddingDimensions: null,
      embeddingDedupThreshold: 0.92,
      embeddingBackfillOnStart: false
    }
  }
}

export function normalizeMemorySettings(input: MemorySettingsPatchV1 | undefined): MemorySettingsV1 {
  const defaults = defaultMemorySettings()
  const source = input ?? {}
  const smart = source.smart ?? {}
  const rawDimensions = smart.embeddingDimensions
  return {
    enabled: normalizeBoolean(source.enabled, defaults.enabled),
    mode: normalizeMemoryMode(source.mode),
    smart: {
      enabled: normalizeBoolean(smart.enabled, defaults.smart.enabled),
      dataDir: typeof smart.dataDir === 'string' ? smart.dataDir.trim() : defaults.smart.dataDir,
      recallEnabled: normalizeBoolean(smart.recallEnabled, defaults.smart.recallEnabled),
      captureEnabled: normalizeBoolean(smart.captureEnabled, defaults.smart.captureEnabled),
      recallTimeoutMs: normalizePositiveInteger(
        smart.recallTimeoutMs,
        defaults.smart.recallTimeoutMs,
        250,
        30_000
      ),
      recallScoreThreshold: normalizeNumber(
        smart.recallScoreThreshold,
        defaults.smart.recallScoreThreshold,
        0,
        1
      ),
      recallLimit: normalizePositiveInteger(smart.recallLimit, defaults.smart.recallLimit, 1, 20),
      captureMinUserChars: normalizePositiveInteger(
        smart.captureMinUserChars,
        defaults.smart.captureMinUserChars,
        0,
        500
      ),
      l1EveryN: normalizePositiveInteger(smart.l1EveryN, defaults.smart.l1EveryN, 1, 100),
      l1IdleTimeoutSeconds: normalizePositiveInteger(
        smart.l1IdleTimeoutSeconds,
        defaults.smart.l1IdleTimeoutSeconds,
        5,
        86_400
      ),
      l1ConfidenceMin: normalizeNumber(
        smart.l1ConfidenceMin,
        defaults.smart.l1ConfidenceMin,
        0,
        1
      ),
      l1MaxPerSession: normalizePositiveInteger(
        smart.l1MaxPerSession,
        defaults.smart.l1MaxPerSession,
        1,
        100
      ),
      l1DecayHalfLifeDays: normalizePositiveInteger(
        smart.l1DecayHalfLifeDays,
        defaults.smart.l1DecayHalfLifeDays,
        0,
        3650
      ),
      hybridSearch: normalizeBoolean(smart.hybridSearch, defaults.smart.hybridSearch),
      ftsTokenizer: normalizeFtsTokenizer(smart.ftsTokenizer),
      embeddingProvider: normalizeEmbeddingProvider(smart.embeddingProvider),
      embeddingModel:
        typeof smart.embeddingModel === 'string' && smart.embeddingModel.trim()
          ? smart.embeddingModel.trim()
          : defaults.smart.embeddingModel,
      embeddingBaseUrl:
        typeof smart.embeddingBaseUrl === 'string' ? smart.embeddingBaseUrl.trim() : '',
      embeddingApiKey:
        typeof smart.embeddingApiKey === 'string' ? smart.embeddingApiKey.trim() : '',
      embeddingDimensions:
        rawDimensions == null
          ? null
          : normalizePositiveInteger(rawDimensions, defaults.smart.embeddingDimensions ?? 3072, 1, 10_000),
      embeddingDedupThreshold: normalizeNumber(
        smart.embeddingDedupThreshold,
        defaults.smart.embeddingDedupThreshold,
        0,
        1
      ),
      embeddingBackfillOnStart: normalizeBoolean(
        smart.embeddingBackfillOnStart,
        defaults.smart.embeddingBackfillOnStart
      )
    }
  }
}

export function mergeMemorySettings(
  current: MemorySettingsV1 | undefined,
  patch: MemorySettingsPatchV1 | undefined
): MemorySettingsV1 {
  const base = current ?? defaultMemorySettings()
  if (!patch) return normalizeMemorySettings(base)
  return normalizeMemorySettings({
    ...base,
    ...patch,
    smart: {
      ...base.smart,
      ...(patch.smart ?? {})
    }
  })
}

export function defaultClawSettings(): ClawSettingsV1 {
  return {
    enabled: false,
    skills: {
      defaultNames: [],
      extraDirs: [],
      promptPrefix: ''
    },
    im: {
      enabled: false,
      provider: 'feishu',
      port: 8787,
      path: '/claw/im',
      secret: '',
      feishuReceiveId: '',
      workspaceRoot: '',
      model: DEFAULT_CLAW_MODEL,
      mode: 'agent',
      responseTimeoutMs: 120_000
    },
    channels: [],
    tasks: []
  }
}

export function normalizeClawSettings(input: ClawSettingsPatchV1 | undefined): ClawSettingsV1 {
  const defaults = defaultClawSettings()
  const source = input ?? {}
  const skills = source.skills ?? defaults.skills
  const im = source.im ?? defaults.im
  const rawChannels = Array.isArray(source.channels)
    ? source.channels.filter((channel) => {
        const raw = channel as Partial<ClawImChannelV1>
        return raw.provider === undefined || raw.provider === null || raw.provider === 'feishu'
      })
    : []
  const now = new Date().toISOString()
  return {
    enabled: normalizeBoolean(source.enabled, defaults.enabled),
    skills: {
      defaultNames: compactStrings(skills.defaultNames),
      extraDirs: compactStrings(skills.extraDirs),
      promptPrefix: typeof skills.promptPrefix === 'string' ? skills.promptPrefix : ''
    },
    im: {
      enabled: normalizeBoolean(im.enabled, defaults.im.enabled),
      provider: normalizeImProvider(im.provider),
      port: normalizePositiveInteger(im.port, defaults.im.port, 1024, 65_535),
      path: normalizePathSegment(im.path),
      secret: typeof im.secret === 'string' ? im.secret.trim() : '',
      feishuReceiveId:
        typeof im.feishuReceiveId === 'string' ? im.feishuReceiveId.trim() : defaults.im.feishuReceiveId,
      workspaceRoot: typeof im.workspaceRoot === 'string' ? im.workspaceRoot.trim() : '',
      model: typeof im.model === 'string' && im.model.trim() ? im.model.trim() : DEFAULT_CLAW_MODEL,
      mode: normalizeRunMode(im.mode),
      responseTimeoutMs: normalizePositiveInteger(im.responseTimeoutMs, defaults.im.responseTimeoutMs, 5_000, 600_000)
    },
    channels: rawChannels
      .map((channel, index): ClawImChannelV1 => {
          const raw = channel as Partial<ClawImChannelV1>
          const provider = normalizeImProvider(raw.provider)
          return {
            id: typeof raw.id === 'string' && raw.id.trim() ? raw.id.trim() : `im-${index + 1}`,
            provider,
            label: typeof raw.label === 'string' && raw.label.trim() ? raw.label.trim() : provider,
            enabled: normalizeBoolean(raw.enabled, true),
            model: normalizeClawModel(raw.model),
            threadId: typeof raw.threadId === 'string' ? raw.threadId.trim() : '',
            workspaceRoot: typeof raw.workspaceRoot === 'string' ? raw.workspaceRoot.trim() : '',
            agentProfile: normalizeClawImAgentProfile(raw.agentProfile),
            platformCredential: normalizeClawImPlatformCredential(raw.platformCredential),
            remoteSession: normalizeClawImRemoteSession(raw.remoteSession),
            conversations: Array.isArray(raw.conversations)
              ? raw.conversations
                  .map((conversation) => normalizeClawImConversation(conversation))
                  .filter((conversation): conversation is ClawImConversationV1 => conversation != null)
              : [],
            createdAt: typeof raw.createdAt === 'string' && raw.createdAt ? raw.createdAt : now,
            updatedAt: typeof raw.updatedAt === 'string' && raw.updatedAt ? raw.updatedAt : now
          }
        }),
    tasks: Array.isArray(source.tasks)
      ? source.tasks.map((task, index): ClawTaskV1 => {
          const raw = task as Partial<ClawTaskV1>
          const schedule = raw.schedule ?? defaults.tasks[index]?.schedule
          return {
            id: typeof raw.id === 'string' && raw.id.trim() ? raw.id.trim() : `task-${index + 1}`,
            title: typeof raw.title === 'string' && raw.title.trim() ? raw.title.trim() : `Task ${index + 1}`,
            enabled: normalizeBoolean(raw.enabled, true),
            prompt: typeof raw.prompt === 'string' ? raw.prompt : '',
            workspaceRoot: typeof raw.workspaceRoot === 'string' ? raw.workspaceRoot.trim() : '',
            model: typeof raw.model === 'string' && raw.model.trim() ? raw.model.trim() : DEFAULT_CLAW_MODEL,
            mode: normalizeRunMode(raw.mode),
            schedule: {
              kind: normalizeScheduleKind(schedule?.kind),
              everyMinutes: normalizePositiveInteger(schedule?.everyMinutes, 60, 1, 10_080),
              timeOfDay: normalizeTimeOfDay(schedule?.timeOfDay),
              atTime: normalizeAtTime(schedule?.atTime)
            },
            createdAt: typeof raw.createdAt === 'string' && raw.createdAt ? raw.createdAt : now,
            updatedAt: typeof raw.updatedAt === 'string' && raw.updatedAt ? raw.updatedAt : now,
            lastRunAt: typeof raw.lastRunAt === 'string' ? raw.lastRunAt : '',
            nextRunAt: typeof raw.nextRunAt === 'string' ? raw.nextRunAt : '',
            lastStatus: normalizeStatus(raw.lastStatus),
            lastMessage: typeof raw.lastMessage === 'string' ? raw.lastMessage : '',
            lastThreadId: typeof raw.lastThreadId === 'string' ? raw.lastThreadId : ''
          }
        })
      : []
  }
}

export function mergeClawSettings(
  current: ClawSettingsV1,
  patch: ClawSettingsPatchV1 | undefined
): ClawSettingsV1 {
  if (!patch) return normalizeClawSettings(current)
  return normalizeClawSettings({
    ...current,
    ...patch,
    skills: {
      ...current.skills,
      ...(patch.skills ?? {})
    },
    im: {
      ...current.im,
      ...(patch.im ?? {})
    },
    channels: patch.channels ?? current.channels,
    tasks: patch.tasks ?? current.tasks
  })
}

export function defaultWorkbenchSkills(): WorkbenchSkillsConfigV1 {
  return { extraDirs: [] }
}

export function normalizeWorkbenchSkills(
  input: Partial<WorkbenchSkillsConfigV1> | undefined,
  legacyClawExtraDirs?: string[]
): WorkbenchSkillsConfigV1 {
  const source = input ?? {}
  const fromLegacy = legacyClawExtraDirs ?? []
  const merged = source.extraDirs?.length ? source.extraDirs : fromLegacy
  return { extraDirs: compactStrings(merged) }
}

function normalizeLlmProviderConfig(raw: unknown): LlmProviderConfigV1 {
  const source =
    raw && typeof raw === 'object'
      ? (raw as Partial<LlmProviderConfigV1> & { enabledModels?: unknown })
      : {}
  const models = migrateEnabledModelsToModels(
    source.enabledModels,
    normalizeLlmProviderModels(source.models)
  )
  const lastFetchedModels = Array.isArray(source.lastFetchedModels)
    ? source.lastFetchedModels
        .filter((id): id is string => typeof id === 'string')
        .map((id) => id.trim())
        .filter(Boolean)
    : undefined
  return {
    apiKey: typeof source.apiKey === 'string' ? source.apiKey.trim() : '',
    models,
    ...(lastFetchedModels && lastFetchedModels.length > 0
      ? { lastFetchedModels: [...new Set(lastFetchedModels)] }
      : {})
  }
}

/**
 * Normalize built-in provider map and keep DeepSeek key/url bi-directionally
 * synced with legacy `deepseek.*` fields.
 */
export function normalizeLlmProviders(
  input: unknown,
  deepseek: DeepseekSettingsV1,
  defaultProviderId?: unknown
): {
  defaultLlmProviderId: BuiltinLlmProviderId
  llmProviders: Record<BuiltinLlmProviderId, LlmProviderConfigV1>
  deepseek: DeepseekSettingsV1
} {
  const defaults = defaultLlmProviders()
  const raw =
    input && typeof input === 'object'
      ? (input as Partial<Record<BuiltinLlmProviderId, unknown>>)
      : {}
  const llmProviders = { ...defaults }
  for (const id of BUILTIN_LLM_PROVIDER_IDS) {
    llmProviders[id] = normalizeLlmProviderConfig(raw[id] ?? defaults[id])
  }

  // Migrate legacy deepseek.apiKey → llmProviders.deepseek when empty.
  const migratedDeepseekKey =
    !llmProviders.deepseek.apiKey && Boolean(deepseek.apiKey.trim())
  if (migratedDeepseekKey) {
    llmProviders.deepseek = {
      ...llmProviders.deepseek,
      apiKey: deepseek.apiKey.trim()
    }
  }
  // Seed DeepSeek models once when migrating a legacy key with no picks.
  if (migratedDeepseekKey && llmProviders.deepseek.models.length === 0) {
    llmProviders.deepseek = {
      ...llmProviders.deepseek,
      models: BUILTIN_LLM_PROVIDERS.deepseek.fallbackModels.map((id) => ({
        id,
        enabled: true,
        contextWindow: CUSTOM_MODEL_CONTEXT_WINDOW_DEFAULT
      }))
    }
  }

  // Mirror DeepSeek vendor config back onto legacy fields for old call sites.
  const lockedDeepseekUrl = BUILTIN_LLM_PROVIDERS.deepseek.baseUrl
  const nextDeepseek: DeepseekSettingsV1 = {
    ...deepseek,
    apiKey: llmProviders.deepseek.apiKey,
    baseUrl: lockedDeepseekUrl
  }

  let defaultLlmProviderId: BuiltinLlmProviderId = isBuiltinLlmProviderId(defaultProviderId)
    ? defaultProviderId
    : DEFAULT_LLM_PROVIDER_ID
  // Unconfigured vendors cannot be the default — prefer DeepSeek, else first with a key.
  if (!llmProviders[defaultLlmProviderId].apiKey.trim()) {
    defaultLlmProviderId =
      BUILTIN_LLM_PROVIDER_IDS.find((id) => llmProviders[id].apiKey.trim()) ??
      DEFAULT_LLM_PROVIDER_ID
  }

  return { defaultLlmProviderId, llmProviders, deepseek: nextDeepseek }
}

export function mergeLlmProviders(
  current: Record<BuiltinLlmProviderId, LlmProviderConfigV1>,
  patch: Partial<Record<BuiltinLlmProviderId, Partial<LlmProviderConfigV1>>> | undefined
): Record<BuiltinLlmProviderId, LlmProviderConfigV1> {
  if (!patch) return current
  const next = { ...current }
  for (const id of BUILTIN_LLM_PROVIDER_IDS) {
    const part = patch[id]
    if (!part) continue
    next[id] = normalizeLlmProviderConfig({
      ...current[id],
      ...part,
      models: part.models ?? current[id].models,
      lastFetchedModels: part.lastFetchedModels ?? current[id].lastFetchedModels
    })
  }
  return next
}

export function defaultAsrProviders(): AsrProviderV1[] {
  return [
    {
      id: BUILTIN_ASR_PROVIDER_ID,
      name: '智谱 ASR',
      baseUrl: DEFAULT_ASR_BASE_URL,
      apiKey: '',
      models: [{ id: DEFAULT_ASR_MODEL, enabled: true }],
      builtin: true
    }
  ]
}

export function resolveActiveAsrSettings(providers: AsrProviderV1[]): AsrSettingsV1 {
  const active =
    providers.find(
      (provider) =>
        Boolean(provider.apiKey.trim()) && provider.models.some((model) => model.enabled)
    ) ??
    providers.find((provider) => provider.builtin) ??
    providers[0]
  const model =
    active?.models.find((entry) => entry.enabled)?.id?.trim() ||
    active?.models[0]?.id?.trim() ||
    DEFAULT_ASR_MODEL
  return {
    apiKey: active?.apiKey?.trim() ?? '',
    baseUrl: (active?.baseUrl?.trim() || DEFAULT_ASR_BASE_URL),
    model
  }
}

export function normalizeAsrProviders(
  raw: unknown,
  legacy?: Partial<AsrSettingsV1> | null
): AsrProviderV1[] {
  const usedIds = new Set<string>()
  const list: AsrProviderV1[] = []
  if (Array.isArray(raw)) {
    for (const row of raw) {
      if (!row || typeof row !== 'object') continue
      const source = row as Partial<AsrProviderV1>
      const name = typeof source.name === 'string' ? source.name.trim() : ''
      if (!name) continue
      const fallbackId =
        `${name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'asr'}-${list.length + 1}`
      const rawId = typeof source.id === 'string' && source.id.trim() ? source.id.trim() : fallbackId
      let id = rawId.toLowerCase().replace(/[^a-z0-9_-]+/g, '-').replace(/^-|-$/g, '') || fallbackId
      let suffix = 2
      while (usedIds.has(id)) {
        id = `${rawId}-${suffix}`
        suffix += 1
      }
      usedIds.add(id)
      const modelsRaw = Array.isArray(source.models) ? source.models : []
      const seenModels = new Set<string>()
      const models: AsrProviderModelV1[] = []
      for (const model of modelsRaw) {
        if (!model || typeof model !== 'object') continue
        const modelId = typeof model.id === 'string' ? model.id.trim() : ''
        if (!modelId || seenModels.has(modelId)) continue
        seenModels.add(modelId)
        models.push({ id: modelId, enabled: model.enabled !== false })
      }
      const builtin = source.builtin === true || id === BUILTIN_ASR_PROVIDER_ID
      if (models.length === 0 && builtin) {
        models.push({ id: DEFAULT_ASR_MODEL, enabled: true })
      }
      list.push({
        id,
        name,
        baseUrl:
          typeof source.baseUrl === 'string' && source.baseUrl.trim()
            ? source.baseUrl.trim()
            : DEFAULT_ASR_BASE_URL,
        apiKey: typeof source.apiKey === 'string' ? source.apiKey.trim() : '',
        models,
        ...(builtin ? { builtin: true } : {})
      })
    }
  }

  const hasBuiltin = list.some((provider) => provider.id === BUILTIN_ASR_PROVIDER_ID)
  if (!hasBuiltin) {
    const seeded = defaultAsrProviders()[0]
    const legacyKey = typeof legacy?.apiKey === 'string' ? legacy.apiKey.trim() : ''
    const legacyModel =
      typeof legacy?.model === 'string' && legacy.model.trim()
        ? legacy.model.trim()
        : DEFAULT_ASR_MODEL
    const legacyUrl =
      typeof legacy?.baseUrl === 'string' && legacy.baseUrl.trim()
        ? legacy.baseUrl.trim()
        : DEFAULT_ASR_BASE_URL
    list.unshift({
      ...seeded,
      apiKey: legacyKey,
      baseUrl: legacyUrl,
      models: [{ id: legacyModel, enabled: true }]
    })
  } else if (legacy) {
    const builtin = list.find((provider) => provider.id === BUILTIN_ASR_PROVIDER_ID)
    if (builtin && !builtin.apiKey.trim() && typeof legacy.apiKey === 'string' && legacy.apiKey.trim()) {
      builtin.apiKey = legacy.apiKey.trim()
      if (typeof legacy.baseUrl === 'string' && legacy.baseUrl.trim()) {
        builtin.baseUrl = legacy.baseUrl.trim()
      }
      const legacyModel =
        typeof legacy.model === 'string' && legacy.model.trim()
          ? legacy.model.trim()
          : DEFAULT_ASR_MODEL
      if (!builtin.models.some((model) => model.id === legacyModel)) {
        builtin.models = [{ id: legacyModel, enabled: true }, ...builtin.models]
      } else {
        builtin.models = builtin.models.map((model) =>
          model.id === legacyModel ? { ...model, enabled: true } : model
        )
      }
    }
  }

  return list
}

export function normalizeCustomEndpoints(endpoints: unknown): CustomEndpointV1[] {
  if (!Array.isArray(endpoints)) return []
  const usedEndpointIds = new Set<string>([...BUILTIN_LLM_PROVIDER_IDS])
  return endpoints
    .filter((ep): ep is Record<string, unknown> => typeof ep === 'object' && ep !== null)
    .filter((ep) => typeof ep.name === 'string' && ep.name.trim())
    .map((ep, index) => {
      const name = String(ep.name).trim()
      const fallbackId = `${name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'endpoint'}-${index + 1}`
      const rawId = typeof ep.id === 'string' && ep.id.trim() ? ep.id.trim() : fallbackId
      const requestedId = rawId.toLowerCase().replace(/[^a-z0-9_-]+/g, '-').replace(/^-|-$/g, '') || fallbackId
      let endpointId = requestedId
      let endpointSuffix = 2
      while (usedEndpointIds.has(endpointId)) {
        endpointId = `${requestedId}-${endpointSuffix}`
        endpointSuffix += 1
      }
      usedEndpointIds.add(endpointId)
      const rawModels = Array.isArray(ep.models)
        ? ep.models
        : typeof ep.model === 'string' && ep.model.trim()
          ? [{ id: ep.model, enabled: true, testStatus: 'untested' }]
          : []
      const seen = new Set<string>()
      const models = rawModels
        .filter((model): model is Record<string, unknown> => typeof model === 'object' && model !== null)
        .map((model): CustomEndpointModelV1 => ({
          id: typeof model.id === 'string' ? model.id.trim() : '',
          label: typeof model.label === 'string' && model.label.trim() ? model.label.trim() : undefined,
          enabled: model.enabled !== false,
          contextWindow: normalizeCustomModelContextWindow(model.contextWindow),
          testStatus: model.testStatus === 'passed' || model.testStatus === 'failed'
            ? model.testStatus
            : 'untested',
          toolCalling: typeof model.toolCalling === 'boolean' ? model.toolCalling : undefined,
          lastTestedAt: typeof model.lastTestedAt === 'string' ? model.lastTestedAt : undefined
        }))
        .filter((model) => {
          if (!model.id || seen.has(model.id)) return false
          seen.add(model.id)
          return true
        })
      return {
        id: endpointId,
        name,
        protocol: ep.protocol === 'anthropic' ? 'anthropic' : 'openai',
        baseUrl: typeof ep.baseUrl === 'string' ? ep.baseUrl.trim() : '',
        apiKey: typeof ep.apiKey === 'string' ? ep.apiKey.trim() : '',
        enabled: ep.enabled !== false,
        models
      }
    })
}

export function normalizeUiFontFamily(_raw: unknown): UiFontFamily {
  // UI font is fixed to the system-native (Mac PingFang / Windows YaHei) stack;
  // the selector was removed, so any stored/legacy value resolves here.
  return 'system-native'
}

export function normalizeAppSettings(settings: AppSettingsV1): AppSettingsV1 {
  const maybeSettings = settings as AppSettingsV1 & {
    notifications?: Partial<NotificationConfigV1>
    skills?: Partial<WorkbenchSkillsConfigV1>
    memory?: MemorySettingsPatchV1
    claw?: ClawSettingsPatchV1
    guiUpdate?: Partial<GuiUpdateConfigV1>
    appearance?: AppearancePatchV1
    shortcuts?: ShortcutsPatchV1 | ShortcutsSettingsV1
    llmProviders?: unknown
    defaultLlmProviderId?: unknown
  }
  const claw = normalizeClawSettings(maybeSettings.claw)
  const deepseekBase = {
    ...settings.deepseek,
    baseUrl: normalizeDeepseekBaseUrl(settings.deepseek.baseUrl),
    // Keep sandbox derived from the approval tier so the three-mode dial
    // remains the single permission control.
    sandboxMode: sandboxModeForApprovalPolicy(settings.deepseek.approvalPolicy)
  }
  const llm = normalizeLlmProviders(
    maybeSettings.llmProviders,
    deepseekBase,
    maybeSettings.defaultLlmProviderId
  )
  return {
    ...settings,
    uiFontFamily: normalizeUiFontFamily(settings.uiFontFamily),
    deepseek: llm.deepseek,
    defaultLlmProviderId: llm.defaultLlmProviderId,
    llmProviders: llm.llmProviders,
    customEndpoints: normalizeCustomEndpoints(maybeSettings.customEndpoints),
    asrProviders: normalizeAsrProviders(
      (maybeSettings as { asrProviders?: unknown }).asrProviders
    ),
    notifications: {
      turnComplete: maybeSettings.notifications?.turnComplete !== false
    },
    skills: normalizeWorkbenchSkills(maybeSettings.skills, claw.skills.extraDirs),
    memory: normalizeMemorySettings(maybeSettings.memory),
    claw,
    guiUpdate: {
      channel: normalizeGuiUpdateChannel(
        maybeSettings.guiUpdate?.channel ?? DEFAULT_GUI_UPDATE_CHANNEL
      )
    },
    appearance: normalizeAppearanceSettings(maybeSettings.appearance),
    shortcuts: normalizeShortcutsSettings(maybeSettings.shortcuts)
  }
}

export {
  defaultShortcutsSettings,
  mergeAppearanceSettings,
  mergeShortcutsSettings,
  normalizeAppearanceSettings,
  normalizeShortcutsSettings
}
export type {
  AppearancePatchV1,
  AppearanceSettingsV1,
  ShortcutsPatchV1,
  ShortcutsSettingsV1
}
