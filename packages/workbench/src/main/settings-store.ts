import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { homedir } from 'node:os'
import { basename, dirname, join } from 'node:path'
import {
  DEFAULT_DEEPSEEK_BASE_URL,
  defaultClawSettings,
  defaultMemorySettings,
  defaultWorkbenchSkills,
  mergeClawSettings,
  mergeMemorySettings,
  normalizeAppSettings,
  normalizeMemorySettings,
  normalizeWorkbenchSkills,
  type AppSettingsPatch,
  type AppSettingsV1,
  type ClawImChannelV1,
  type ClawImConversationV1
} from '../shared/app-settings'
import {
  defaultAppearanceSettings,
  mergeAppearanceSettings,
  normalizeAppearanceSettings
} from '../shared/appearance'
import { DEFAULT_DEV_PREVIEW_URL } from '../shared/dev-preview-url'

export type { AppSettingsV1 }

const DEFAULT_WORKSPACE_ROOT = join(homedir(), '.deepseekgui', 'default_workspace')
const DEFAULT_CLAW_CHANNELS_ROOT = join(homedir(), '.deepseekgui', 'claw')

function expandHomePath(raw: string | null | undefined): string {
  const value = typeof raw === 'string' ? raw.trim() : ''
  if (!value) return ''
  if (value === '~') return homedir()
  if (value.startsWith('~/') || value.startsWith('~\\')) {
    return join(homedir(), value.slice(2))
  }
  return value
}

function normalizeWorkspaceRoot(raw: string | null | undefined): string {
  return expandHomePath(raw) || DEFAULT_WORKSPACE_ROOT
}

function sanitizePathSegment(raw: string | null | undefined, fallback: string): string {
  const value = typeof raw === 'string' ? raw.trim() : ''
  const sanitized = value
    .replace(/[\\/]/g, '-')
    .replace(/[^A-Za-z0-9._-]+/g, '-')
    .replace(/^-+|-+$/g, '')
  return sanitized || fallback
}

function defaultClawChannelWorkspaceRoot(channel: ClawImChannelV1): string {
  const domain = sanitizePathSegment(channel.platformCredential?.domain, 'feishu')
  const workspaceId = sanitizePathSegment(channel.platformCredential?.appId || channel.id, 'channel')
  return join(DEFAULT_CLAW_CHANNELS_ROOT, channel.provider, domain, workspaceId)
}

function normalizeClawChannelWorkspaceRoot(channel: ClawImChannelV1): string {
  return expandHomePath(channel.workspaceRoot) || defaultClawChannelWorkspaceRoot(channel)
}

function sanitizeConversationWorkspaceSegment(conversation: ClawImConversationV1): string {
  return sanitizePathSegment(
    conversation.remoteThreadId || conversation.chatId,
    conversation.id || 'conversation'
  )
}

function defaultClawConversationWorkspaceRoot(
  channel: ClawImChannelV1,
  conversation: ClawImConversationV1
): string {
  return join(normalizeClawChannelWorkspaceRoot(channel), 'conversations', sanitizeConversationWorkspaceSegment(conversation))
}

function normalizeClawConversationWorkspaceRoot(
  channel: ClawImChannelV1,
  conversation: ClawImConversationV1
): string {
  return expandHomePath(conversation.workspaceRoot) || defaultClawConversationWorkspaceRoot(channel, conversation)
}

function normalizeStoredSettings(settings: AppSettingsV1): AppSettingsV1 {
  const normalized = normalizeAppSettings(settings)
  return {
    ...normalized,
    workspaceRoot: normalizeWorkspaceRoot(normalized.workspaceRoot),
    claw: {
      ...normalized.claw,
      channels: normalized.claw.channels.map((channel) => ({
        ...channel,
        workspaceRoot: normalizeClawChannelWorkspaceRoot(channel),
        conversations: channel.conversations.map((conversation) => ({
          ...conversation,
          workspaceRoot: normalizeClawConversationWorkspaceRoot(channel, conversation)
        }))
      }))
    }
  }
}

async function ensureWorkspaceRootExists(workspaceRoot: string): Promise<void> {
  if (workspaceRoot !== DEFAULT_WORKSPACE_ROOT) return
  await mkdir(workspaceRoot, { recursive: true })
}

async function ensureClawChannelWorkspaceRootsExist(settings: AppSettingsV1): Promise<void> {
  for (const channel of settings.claw.channels) {
    const workspaceRoot = normalizeClawChannelWorkspaceRoot(channel)
    if (!workspaceRoot) continue
    await mkdir(workspaceRoot, { recursive: true })
    for (const conversation of channel.conversations) {
      const conversationWorkspaceRoot = normalizeClawConversationWorkspaceRoot(channel, conversation)
      if (!conversationWorkspaceRoot) continue
      await mkdir(conversationWorkspaceRoot, { recursive: true })
    }
  }
}

const defaultSettings = (): AppSettingsV1 => ({
  version: 1,
  locale: 'en',
  theme: 'system',
  uiFontScale: 'small',
  agentProvider: 'deepseek-runtime',
  deepseek: {
    binaryPath: '',
    port: 7878,
    autoStart: true,
    apiKey: '',
    baseUrl: DEFAULT_DEEPSEEK_BASE_URL,
    runtimeToken: '',
    extraCorsOrigins: ['http://localhost:5173', 'http://127.0.0.1:5173'],
    // Default to on-request so the GUI surfaces an approval dialog before any
    // write tool / shell command runs. Auto used to be the default but it
    // silently bypassed the entire ApprovalBridge — equivalent to running
    // sandbox-disabled. Users can opt back into 'auto' from Settings.
    approvalPolicy: 'on-request',
    sandboxMode: 'workspace-write'
  },
  workspaceRoot: DEFAULT_WORKSPACE_ROOT,
  log: {
    enabled: true,
    retentionDays: 2
  },
  notifications: {
    turnComplete: true
  },
  skills: defaultWorkbenchSkills(),
  memory: defaultMemorySettings(),
  guiUpdate: {
    channel: 'frontier'
  },
  claw: defaultClawSettings(),
  appearance: defaultAppearanceSettings()
})

function buildMergedSettings(parsed: Partial<AppSettingsV1>): AppSettingsV1 {
  const defaults = defaultSettings()
  return {
    ...defaults,
    ...parsed,
    deepseek: { ...defaults.deepseek, ...parsed.deepseek },
    log: { ...defaults.log, ...parsed.log },
    notifications: { ...defaults.notifications, ...parsed.notifications },
    skills: normalizeWorkbenchSkills(parsed.skills, parsed.claw?.skills?.extraDirs),
    memory: normalizeMemorySettings(parsed.memory),
    claw: mergeClawSettings(defaults.claw, parsed.claw),
    guiUpdate: { ...defaults.guiUpdate, ...parsed.guiUpdate },
    appearance: normalizeAppearanceSettings(parsed.appearance),
    agentProvider: 'deepseek-runtime'
  }
}

function isErrnoException(error: unknown): error is NodeJS.ErrnoException {
  return typeof error === 'object' && error !== null
}

async function loadDefaultSettings(): Promise<AppSettingsV1> {
  const defaults = normalizeStoredSettings(defaultSettings())
  await ensureWorkspaceRootExists(defaults.workspaceRoot)
  await ensureClawChannelWorkspaceRootsExist(defaults)
  return defaults
}

async function writeInvalidSettingsBackup(path: string, raw: string): Promise<string | null> {
  const stamp = new Date().toISOString().replace(/[:.]/g, '-')
  const backupPath = join(
    dirname(path),
    `${basename(path, '.json')}.invalid-${stamp}.json`
  )
  try {
    await writeFile(backupPath, raw, 'utf8')
    return backupPath
  } catch {
    return null
  }
}

export class JsonSettingsStore {
  private path: string
  private cache: AppSettingsV1 | null = null

  constructor(userDataPath: string) {
    this.path = join(userDataPath, 'deepseek-gui-settings.json')
  }

  async load(): Promise<AppSettingsV1> {
    if (this.cache) return this.cache

    let raw = ''
    try {
      raw = await readFile(this.path, 'utf8')
    } catch (error) {
      if (isErrnoException(error) && error.code === 'ENOENT') {
        this.cache = await loadDefaultSettings()
        return this.cache
      }
      const message = error instanceof Error ? error.message : String(error)
      throw new Error(`Failed to read settings file ${this.path}: ${message}`, { cause: error })
    }

    let parsed: Partial<AppSettingsV1>
    try {
      parsed = JSON.parse(raw) as Partial<AppSettingsV1>
    } catch (error) {
      if (error instanceof SyntaxError) {
        const backupPath = await writeInvalidSettingsBackup(this.path, raw)
        const defaults = await loadDefaultSettings()
        await this.save(defaults)
        if (backupPath) {
          console.warn(
            `[deepseek-gui] Invalid settings JSON was replaced with defaults. Backup: ${backupPath}`
          )
        } else {
          console.warn(
            `[deepseek-gui] Invalid settings JSON was replaced with defaults. Backup could not be written for ${this.path}.`
          )
        }
        return defaults
      }
      const message = error instanceof Error ? error.message : String(error)
      throw new Error(`Failed to parse settings file ${this.path}: ${message}`, { cause: error })
    }

    const normalized = normalizeStoredSettings(buildMergedSettings(parsed))
    await ensureWorkspaceRootExists(normalized.workspaceRoot)
    await ensureClawChannelWorkspaceRootsExist(normalized)
    this.cache = normalized
    return this.cache
  }

  async save(data: AppSettingsV1): Promise<void> {
    const normalized = normalizeStoredSettings(data)
    await ensureWorkspaceRootExists(normalized.workspaceRoot)
    await ensureClawChannelWorkspaceRootsExist(normalized)
    this.cache = normalized
    await mkdir(dirname(this.path), { recursive: true })
    await writeFile(this.path, JSON.stringify(normalized, null, 2), 'utf8')
  }

  async patch(partial: AppSettingsPatch): Promise<AppSettingsV1> {
    const cur = await this.load()
    const next = normalizeStoredSettings({
      ...cur,
      ...partial,
      deepseek: { ...cur.deepseek, ...(partial.deepseek ?? {}) },
      log: { ...cur.log, ...(partial.log ?? {}) },
      notifications: { ...cur.notifications, ...(partial.notifications ?? {}) },
      skills: normalizeWorkbenchSkills(
        partial.skills ? { ...cur.skills, ...partial.skills } : cur.skills,
        partial.claw?.skills?.extraDirs
      ),
      memory: mergeMemorySettings(cur.memory, partial.memory),
      claw: mergeClawSettings(cur.claw, partial.claw),
      guiUpdate: { ...cur.guiUpdate, ...(partial.guiUpdate ?? {}) },
      appearance: mergeAppearanceSettings(cur.appearance, partial.appearance),
      agentProvider: 'deepseek-runtime'
    })
    await this.save(next)
    return next
  }
}

export function getRuntimeBaseUrl(port: number): string {
  return `http://127.0.0.1:${port}`
}

export function devServerHintUrl(isPackaged = false): string | undefined {
  const fromElectron = process.env.ELECTRON_RENDERER_URL?.trim()
  if (fromElectron) return fromElectron
  const fromVite = process.env.VITE_DEV_SERVER_URL?.trim()
  if (fromVite) return fromVite
  if (!isPackaged) return DEFAULT_DEV_PREVIEW_URL
  return undefined
}
