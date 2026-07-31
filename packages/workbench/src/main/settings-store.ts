import {
  access,
  copyFile,
  cp,
  mkdir,
  readFile,
  readdir,
  rename,
  rm,
  unlink,
  writeFile
} from 'node:fs/promises'
import { homedir } from 'node:os'
import { basename, dirname, join } from 'node:path'
import {
  DEFAULT_DEEPSEEK_BASE_URL,
  DEFAULT_LLM_PROVIDER_ID,
  defaultAsrProviders,
  defaultClawSettings,
  defaultLlmProviders,
  defaultMemorySettings,
  defaultShortcutsSettings,
  defaultWebSearchSettings,
  defaultWorkbenchSkills,
  mergeClawSettings,
  mergeLlmProviders,
  mergeMemorySettings,
  mergeShortcutsSettings,
  mergeWebSearchSettings,
  normalizeAppSettings,
  normalizeAsrProviders,
  normalizeCustomEndpoints,
  normalizeMemorySettings,
  normalizeShortcutsSettings,
  normalizeWebSearchSettings,
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
import { DEFAULT_WORKSPACE_SEGMENTS } from '../shared/workspace-defaults'
import {
  resolveClawChannelsRoot,
  resolveLegacyClawChannelsRoot,
  resolveLegacyGuiSettingsPath,
  resolveWorkbenchSettingsPath
} from '../shared/workbench-home'

export type { AppSettingsV1 }

const DEFAULT_WORKSPACE_ROOT = join(homedir(), ...DEFAULT_WORKSPACE_SEGMENTS)

export type JsonSettingsStoreOptions = {
  /** Electron userData — used to migrate ``deepseek-gui-settings.json``. */
  legacyUserDataPath?: string
  /** Override ``os.homedir()`` for path resolution (tests). */
  home?: string
}

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

function defaultClawChannelWorkspaceRoot(channel: ClawImChannelV1, home?: string): string {
  const domain = sanitizePathSegment(channel.platformCredential?.domain, 'feishu')
  const workspaceId = sanitizePathSegment(channel.platformCredential?.appId || channel.id, 'channel')
  return join(resolveClawChannelsRoot(home), channel.provider, domain, workspaceId)
}

/** Rewrite persisted ``~/.deepseekgui/claw/...`` roots to workbench/claw. */
function rewriteLegacyClawWorkspacePath(raw: string | null | undefined, home?: string): string {
  const expanded = expandHomePath(raw)
  if (!expanded) return ''
  const legacyRoot = resolveLegacyClawChannelsRoot(home)
  const nextRoot = resolveClawChannelsRoot(home)
  if (expanded === legacyRoot || expanded.startsWith(`${legacyRoot}/`) || expanded.startsWith(`${legacyRoot}\\`)) {
    return `${nextRoot}${expanded.slice(legacyRoot.length)}`
  }
  const marker = '/.deepseekgui/claw'
  const idx = expanded.indexOf(marker)
  if (idx >= 0) {
    const prefix = expanded.slice(0, idx)
    const rest = expanded.slice(idx + marker.length)
    return `${join(prefix, '.deepseek', 'workbench', 'claw')}${rest}`
  }
  return expanded
}

function normalizeClawChannelWorkspaceRoot(channel: ClawImChannelV1, home?: string): string {
  return (
    rewriteLegacyClawWorkspacePath(channel.workspaceRoot, home) ||
    defaultClawChannelWorkspaceRoot(channel, home)
  )
}

function sanitizeConversationWorkspaceSegment(conversation: ClawImConversationV1): string {
  return sanitizePathSegment(
    conversation.remoteThreadId || conversation.chatId,
    conversation.id || 'conversation'
  )
}

function defaultClawConversationWorkspaceRoot(
  channel: ClawImChannelV1,
  conversation: ClawImConversationV1,
  home?: string
): string {
  return join(
    normalizeClawChannelWorkspaceRoot(channel, home),
    'conversations',
    sanitizeConversationWorkspaceSegment(conversation)
  )
}

function normalizeClawConversationWorkspaceRoot(
  channel: ClawImChannelV1,
  conversation: ClawImConversationV1,
  home?: string
): string {
  return (
    rewriteLegacyClawWorkspacePath(conversation.workspaceRoot, home) ||
    defaultClawConversationWorkspaceRoot(channel, conversation, home)
  )
}

async function pathExists(path: string): Promise<boolean> {
  try {
    await access(path)
    return true
  } catch {
    return false
  }
}

async function isEmptyDir(path: string): Promise<boolean> {
  try {
    const entries = await readdir(path)
    return entries.length === 0
  } catch {
    return false
  }
}

/** Move legacy ``~/.deepseekgui/claw`` → ``~/.deepseek/workbench/claw`` once. */
async function migrateLegacyClawChannelsRoot(home = homedir()): Promise<boolean> {
  const dest = resolveClawChannelsRoot(home)
  const src = resolveLegacyClawChannelsRoot(home)
  if (!(await pathExists(src))) return false
  if (await pathExists(dest)) {
    // layout.py may have pre-created an empty claw/; treat that as migratable.
    if (!(await isEmptyDir(dest))) return false
    await rm(dest, { recursive: true, force: true })
  }
  await mkdir(dirname(dest), { recursive: true })
  try {
    await rename(src, dest)
  } catch {
    await cp(src, dest, { recursive: true })
    await rm(src, { recursive: true, force: true })
  }
  return true
}

function normalizeStoredSettings(settings: AppSettingsV1, home?: string): AppSettingsV1 {
  const normalized = normalizeAppSettings(settings)
  return {
    ...normalized,
    workspaceRoot: normalizeWorkspaceRoot(normalized.workspaceRoot),
    claw: {
      ...normalized.claw,
      channels: normalized.claw.channels.map((channel) => ({
        ...channel,
        workspaceRoot: normalizeClawChannelWorkspaceRoot(channel, home),
        conversations: channel.conversations.map((conversation) => ({
          ...conversation,
          workspaceRoot: normalizeClawConversationWorkspaceRoot(channel, conversation, home)
        }))
      }))
    }
  }
}

async function ensureWorkspaceRootExists(workspaceRoot: string): Promise<void> {
  if (workspaceRoot !== DEFAULT_WORKSPACE_ROOT) return
  await mkdir(workspaceRoot, { recursive: true })
}

async function ensureClawChannelWorkspaceRootsExist(
  settings: AppSettingsV1,
  home?: string
): Promise<void> {
  await migrateLegacyClawChannelsRoot(home)
  for (const channel of settings.claw.channels) {
    const workspaceRoot = normalizeClawChannelWorkspaceRoot(channel, home)
    if (!workspaceRoot) continue
    await mkdir(workspaceRoot, { recursive: true })
    for (const conversation of channel.conversations) {
      const conversationWorkspaceRoot = normalizeClawConversationWorkspaceRoot(
        channel,
        conversation,
        home
      )
      if (!conversationWorkspaceRoot) continue
      await mkdir(conversationWorkspaceRoot, { recursive: true })
    }
  }
}

const defaultSettings = (): AppSettingsV1 => ({
  version: 1,
  locale: 'zh',
  theme: 'dark',
  uiFontScale: 'medium',
  uiFontFamily: 'system-native',
  iconAnimation: false,
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
  defaultLlmProviderId: DEFAULT_LLM_PROVIDER_ID,
  llmProviders: defaultLlmProviders(),
  customEndpoints: [],
  asrProviders: defaultAsrProviders(),
  webSearch: defaultWebSearchSettings(),
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
  appearance: defaultAppearanceSettings(),
  shortcuts: defaultShortcutsSettings()
})

function buildMergedSettings(parsed: Partial<AppSettingsV1>): AppSettingsV1 {
  const defaults = defaultSettings()
  return {
    ...defaults,
    ...parsed,
    deepseek: { ...defaults.deepseek, ...parsed.deepseek },
    defaultLlmProviderId: parsed.defaultLlmProviderId ?? defaults.defaultLlmProviderId,
    llmProviders: mergeLlmProviders(defaults.llmProviders, parsed.llmProviders),
    customEndpoints: normalizeCustomEndpoints(parsed.customEndpoints ?? defaults.customEndpoints),
    asrProviders: normalizeAsrProviders(parsed.asrProviders ?? defaults.asrProviders),
    webSearch: normalizeWebSearchSettings(parsed.webSearch ?? defaults.webSearch),
    log: { ...defaults.log, ...parsed.log },
    notifications: { ...defaults.notifications, ...parsed.notifications },
    skills: normalizeWorkbenchSkills(parsed.skills, parsed.claw?.skills?.extraDirs),
    memory: normalizeMemorySettings(parsed.memory),
    claw: mergeClawSettings(defaults.claw, parsed.claw),
    guiUpdate: { ...defaults.guiUpdate, ...parsed.guiUpdate },
    appearance: normalizeAppearanceSettings(parsed.appearance),
    shortcuts: normalizeShortcutsSettings(parsed.shortcuts),
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
  private legacySettingsPath: string | null
  private home: string | undefined
  private cache: AppSettingsV1 | null = null

  constructor(options: JsonSettingsStoreOptions = {}) {
    this.home = options.home
    this.path = resolveWorkbenchSettingsPath(options.home)
    this.legacySettingsPath = options.legacyUserDataPath
      ? resolveLegacyGuiSettingsPath(options.legacyUserDataPath)
      : null
  }

  private async migrateLegacySettingsIfNeeded(): Promise<void> {
    if (await pathExists(this.path)) return
    const legacy = this.legacySettingsPath
    if (!legacy || !(await pathExists(legacy))) return
    await mkdir(dirname(this.path), { recursive: true })
    try {
      await rename(legacy, this.path)
    } catch {
      await copyFile(legacy, this.path)
      try {
        await unlink(legacy)
      } catch {
        // Best-effort; new path is authoritative.
      }
    }
  }

  async load(): Promise<AppSettingsV1> {
    if (this.cache) return this.cache

    await this.migrateLegacySettingsIfNeeded()

    let raw = ''
    try {
      raw = await readFile(this.path, 'utf8')
    } catch (error) {
      if (isErrnoException(error) && error.code === 'ENOENT') {
        this.cache = await loadDefaultSettings()
        await this.save(this.cache)
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
        this.cache = defaults
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

    const normalized = normalizeStoredSettings(buildMergedSettings(parsed), this.home)
    await ensureWorkspaceRootExists(normalized.workspaceRoot)
    await ensureClawChannelWorkspaceRootsExist(normalized, this.home)
    this.cache = normalized
    return this.cache
  }

  async save(data: AppSettingsV1): Promise<void> {
    const normalized = normalizeStoredSettings(data, this.home)
    await ensureWorkspaceRootExists(normalized.workspaceRoot)
    await ensureClawChannelWorkspaceRootsExist(normalized, this.home)
    this.cache = normalized
    await mkdir(dirname(this.path), { recursive: true })
    await writeFile(this.path, JSON.stringify(normalized, null, 2), 'utf8')
  }

  async patch(partial: AppSettingsPatch): Promise<AppSettingsV1> {
    const cur = await this.load()
    const next = normalizeStoredSettings(
      {
        ...cur,
        ...partial,
        deepseek: { ...cur.deepseek, ...(partial.deepseek ?? {}) },
        llmProviders: mergeLlmProviders(cur.llmProviders, partial.llmProviders),
        customEndpoints: partial.customEndpoints ?? cur.customEndpoints,
        asrProviders: partial.asrProviders
          ? normalizeAsrProviders(partial.asrProviders)
          : cur.asrProviders,
        webSearch: partial.webSearch
          ? mergeWebSearchSettings(cur.webSearch, partial.webSearch)
          : cur.webSearch,
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
        shortcuts: mergeShortcutsSettings(cur.shortcuts, partial.shortcuts),
        agentProvider: 'deepseek-runtime'
      },
      this.home
    )
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
