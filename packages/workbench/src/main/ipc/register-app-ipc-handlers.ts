import { dialog, ipcMain, shell, type BrowserWindow } from 'electron'
import { homedir } from 'node:os'
import { dirname, join, relative, resolve } from 'node:path'
import { access, mkdir, readdir, readFile, writeFile } from 'node:fs/promises'
import { z } from 'zod'
import type { AppSettingsPatch, AppSettingsV1 } from '../../shared/app-settings'
import type {
  DeepseekRuntimeDiagnosticIssue,
  DeepseekRuntimeDiagnosticsResult,
  RuntimeRequestResult,
  SystemNotificationResult,
  TurnCompleteNotificationPayload,
  UpstreamModelsResult,
  WorkspacePickResult
} from '../../shared/ds-gui-api'
import {
  deepseekConfigContentSchema,
  emailSecretPayloadSchema,
  feishuConfigPayloadSchema,
  wecomConfigPayloadSchema,
  feishuRegisterStartPayloadSchema,
  defaultPathSchema,
  gitBranchPayloadSchema,
  gitCommitPayloadSchema,
  gitCommitPathsPayloadSchema,
  logErrorPayloadSchema,
  notificationPayloadSchema,
  openEditorPathPayloadSchema,
  petResolveSpritesheetPayloadSchema,
  rootPathSchema,
  runtimeRequestPayloadSchema,
  shellOpenExternalUrlSchema,
  skillSaveFilePayloadSchema,
  terminalCreateOptionsSchema,
  terminalInputPayloadSchema,
  terminalLifecyclePayloadSchema,
  terminalResizePayloadSchema,
  trendingPeriodSchema,
  usagePruneEndpointModelPayloadSchema,
  usagePruneProviderPayloadSchema,
  usageQueryPayloadSchema,
  workspaceFileTargetPayloadSchema,
  workspaceFileWritePayloadSchema,
  workspaceListDirectoryPayloadSchema,
  workspacePickFilesPayloadSchema,
  asrTranscribePayloadSchema,
  asrConfigPayloadSchema,
  workspaceRootSchema
} from './app-ipc-schemas'
import type { JsonSettingsStore } from '../settings-store'
import { getRuntimeBaseUrl } from '../settings-store'
import {
  findAlternateDeepseekRuntimes,
  findListeningProcessOnPort,
  formatAlternateRuntimeHint,
  resolveEffectiveRuntimeToken,
  runtimeTokenFilePath
} from '../deepseek-process'
import { commitGitChanges, createAndSwitchGitBranch, getGitBranches, getGitLog, getGitWorkingChanges, suggestGitCommitMessage, switchGitBranch } from '../services/git-service'
import { getTrendingRepos } from '../services/trending-repos'
import { getWorkspaceSuggestions } from '../services/workspace-suggestions'
import { defaultTuiSessionsDir, listTuiSessions } from '../services/tui-session-service'
import { transcribeAudio } from '../services/asr-transcription-service'
import { readAsrConfigFile, writeAsrConfigFile } from '../asr-config'
import {
  parseSessionsProbe,
  parseSkillsProbe,
  parseTasksProbe
} from '../services/runtime-catalog-probes'
import {
  resolveDeepseekConfigPath,
  resolveDeepseekPaths,
  resolveMcpConfigPath,
  resolveUserDeepseekDir
} from '../deepseek-paths'
import { readFeishuConfigFile, writeFeishuConfigFile } from '../feishu-config'
import { readWecomConfigFile, writeWecomConfigFile } from '../wecom-config'
import {
  clearEmailSmtpPassword,
  isEmailSecretStorageAvailable,
  resolveEmailPasswordStatus,
  setEmailSmtpPassword
} from '../channel-secrets'
import { readEmailPasswordEnvKey } from '../email-automation-config'
import {
  cancelFeishuRegisterApp,
  runFeishuRegisterApp,
  type FeishuRegisterTarget
} from '../feishu-register-service'
import { restartDeepseekChildIfRunning } from '../deepseek-process'
import {
  canonicalPath,
  expandHomePath,
  listEditorsResult,
  listWorkspaceDirectory,
  normalizeSkillFolderName,
  openEditorPath,
  openPathWithShell,
  readWorkspaceFile,
  resolveWorkspaceFile,
  writeWorkspaceFile
} from '../services/workspace-service'
import {
  cacheFeaturedPets,
  fetchPetManifest,
  resolvePetSpritesheet
} from '../services/pet-asset-service'
import { usageLedgerService } from '../services/usage-ledger-service'
import type { createTerminalService } from '../services/terminal-service'

type TerminalService = ReturnType<typeof createTerminalService>

type RegisterAppIpcHandlersOptions = {
  store: JsonSettingsStore
  getMainWindow: () => BrowserWindow | null
  applySettingsPatch: (partial: AppSettingsPatch) => Promise<AppSettingsV1>
  runtimeRequest: (
    path: string,
    method?: string,
    body?: string
  ) => Promise<RuntimeRequestResult>
  fetchUpstreamModels: () => Promise<UpstreamModelsResult>
  prepareDeepseekBinary: () => Promise<
    { ok: true; path: string } | { ok: false; message: string }
  >
  resolveDeepseekConfigPath: () => string
  terminalService: TerminalService
  showTurnCompleteNotification: (
    payload: TurnCompleteNotificationPayload
  ) => Promise<SystemNotificationResult>
  getAppVersion: () => string
  resolveLogDirectory: () => string
  logError: (category: string, message: string, detail?: unknown) => void
}

function parseIpcPayload<T>(channel: string, schema: z.ZodType<T>, payload: unknown): T {
  const parsed = schema.safeParse(payload)
  if (parsed.success) return parsed.data
  const issue = parsed.error.issues[0]
  throw new Error(`Invalid payload for ${channel}: ${issue?.message ?? 'Bad request.'}`)
}

const settingsPatchSchema = z.object({}).passthrough()

function trimDiagnosticBody(body: string, max = 2_000): string {
  const text = body.trim()
  if (text.length <= max) return text
  return `${text.slice(0, max)}…`
}

function detectTomlConfigIssues(path: string, content: string): DeepseekRuntimeDiagnosticIssue[] {
  const issues: DeepseekRuntimeDiagnosticIssue[] = []
  const tables = new Map<string, number>()
  const lines = content.split(/\r?\n/)

  for (let index = 0; index < lines.length; index += 1) {
    const trimmed = lines[index].trim()
    if (!trimmed || trimmed.startsWith('#')) continue
    const match = trimmed.match(/^\[([^\][\r\n]+)\]\s*(?:#.*)?$/)
    if (!match) continue
    const tableName = match[1].trim()
    const firstLine = tables.get(tableName)
    if (typeof firstLine === 'number') {
      issues.push({
        severity: 'error',
        code: 'duplicate_toml_table',
        title: 'Duplicate TOML table',
        message: `[${tableName}] is declared again on line ${index + 1}. TOML tables can only be declared once; merge or remove the duplicate block.`,
        path,
        line: index + 1
      })
      continue
    }
    tables.set(tableName, index + 1)
  }

  return issues
}

async function probeRuntimeEndpoint(
  url: string,
  authToken?: string
): Promise<{
  ok: boolean
  status: number
  body: string
  message?: string
}> {
  const headers: Record<string, string> = {}
  if (authToken) {
    headers.Authorization = `Bearer ${authToken}`
  }
  try {
    const res = await fetch(url, { headers, signal: AbortSignal.timeout(2_000) })
    return {
      ok: res.ok,
      status: res.status,
      body: trimDiagnosticBody(await res.text())
    }
  } catch (error) {
    return {
      ok: false,
      status: 0,
      body: '',
      message: error instanceof Error ? error.message : String(error)
    }
  }
}

async function diagnoseDeepseekRuntime(
  options: Pick<RegisterAppIpcHandlersOptions, 'store' | 'prepareDeepseekBinary' | 'resolveDeepseekConfigPath'>
): Promise<DeepseekRuntimeDiagnosticsResult> {
  const settings = await options.store.load()
  const configPath = options.resolveDeepseekConfigPath()
  let configContent = ''
  let configExists = true
  try {
    configContent = await readFile(configPath, 'utf8')
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
      configExists = false
    } else {
      throw error
    }
  }

  const configIssues = detectTomlConfigIssues(configPath, configContent)
  const binary = await options.prepareDeepseekBinary()
  const baseUrl = getRuntimeBaseUrl(settings.deepseek.port)
  const portOwner = await findListeningProcessOnPort(settings.deepseek.port)
  const alternateRuntimes = await findAlternateDeepseekRuntimes(settings.deepseek.port)
  const runtimeToken = resolveEffectiveRuntimeToken(settings) ?? undefined
  const health = await probeRuntimeEndpoint(`${baseUrl}/health`)
  const threadApi = health.ok
    ? await probeRuntimeEndpoint(`${baseUrl}/v1/threads?limit=1`, runtimeToken)
    : null
  const workspaceStatus = health.ok
    ? await probeRuntimeEndpoint(`${baseUrl}/v1/workspace/status`, runtimeToken)
    : null
  const runtimeReady = health.ok && threadApi?.ok === true
  const skillsApi = runtimeReady
    ? await probeRuntimeEndpoint(`${baseUrl}/v1/skills`, runtimeToken)
    : null
  const tasksApi = runtimeReady
    ? await probeRuntimeEndpoint(`${baseUrl}/v1/tasks?limit=50`, runtimeToken)
    : null
  const sessionsApi = runtimeReady
    ? await probeRuntimeEndpoint(`${baseUrl}/v1/sessions?limit=50`, runtimeToken)
    : null
  const issues: DeepseekRuntimeDiagnosticIssue[] = [...configIssues]

  const hasCustomKey = settings.customEndpoints.some(
    (endpoint) => endpoint.enabled && endpoint.apiKey.trim()
  )
  if (!settings.deepseek.apiKey.trim() && !process.env.DEEPSEEK_API_KEY?.trim() && !hasCustomKey) {
    issues.push({
      severity: 'error',
      code: 'missing_api_key',
      title: 'Missing model-provider API key',
      message: 'The GUI cannot auto-start the local runtime until a DeepSeek or custom-provider key is configured.'
    })
  }

  if (!settings.deepseek.autoStart) {
    issues.push({
      severity: 'warning',
      code: 'auto_start_disabled',
      title: 'Automatic runtime startup is disabled',
      message: 'Enable auto-start or run `deepseek serve --http` manually before retrying the connection.'
    })
  }

  if (!binary.ok) {
    issues.push({
      severity: 'error',
      code: 'binary_unavailable',
      title: 'Python runtime is unavailable',
      message: binary.message
    })
  }

  if (!portOwner) {
    issues.push({
      severity: settings.deepseek.autoStart ? 'info' : 'warning',
      code: 'runtime_not_listening',
      title: 'No runtime is listening on the configured port',
      message: `Nothing is listening on ${baseUrl}. Retry will ask the GUI to start the managed runtime.`
    })
    if (alternateRuntimes.length > 0) {
      issues.push({
        severity: 'error',
        code: 'runtime_port_mismatch',
        title: 'Another DeepSeek runtime is listening on a different port',
        message: formatAlternateRuntimeHint(alternateRuntimes, settings.deepseek.port)
      })
    }
  } else if (
    !portOwner.command.toLowerCase().includes('deepseek') &&
    !portOwner.command.toLowerCase().includes('python')
  ) {
    issues.push({
      severity: 'warning',
      code: 'port_owned_by_other_process',
      title: 'Configured port is owned by another process',
      message: `Port ${settings.deepseek.port} is currently owned by PID ${portOwner.pid}: ${portOwner.command}`
    })
  }

  if (health.ok && threadApi && !threadApi.ok) {
    issues.push({
      severity: threadApi.status === 401 ? 'error' : 'warning',
      code: threadApi.status === 401 ? 'runtime_auth_required' : 'thread_api_unavailable',
      title: threadApi.status === 401 ? 'Runtime token mismatch' : 'Thread API check failed',
      message: threadApi.body || threadApi.message || `Thread API returned ${threadApi.status}.`
    })
  }

  return {
    checkedAt: new Date().toISOString(),
    settings: {
      port: settings.deepseek.port,
      autoStart: settings.deepseek.autoStart,
      binaryPath: settings.deepseek.binaryPath,
      baseUrl: settings.deepseek.baseUrl,
      approvalPolicy: settings.deepseek.approvalPolicy,
      sandboxMode: settings.deepseek.sandboxMode,
      hasApiKey: Boolean(settings.deepseek.apiKey.trim() || process.env.DEEPSEEK_API_KEY?.trim()),
      // Reflect the *effective* token (settings override → token file cache),
      // not just the explicit setting — Workbench auto-manages the file so a
      // blank setting is the common case yet auth is wired.
      hasRuntimeToken: Boolean(resolveEffectiveRuntimeToken(settings))
    },
    binary,
    config: {
      path: configPath,
      exists: configExists,
      content: configContent,
      issues: configIssues
    },
    runtime: {
      baseUrl,
      configuredPort: settings.deepseek.port,
      portOwner,
      alternateRuntimes,
      health,
      threadApi,
      workspaceStatus,
      skills: skillsApi ? parseSkillsProbe(skillsApi) : null,
      tasks: tasksApi ? parseTasksProbe(tasksApi) : null,
      sessions: sessionsApi ? parseSessionsProbe(sessionsApi) : null
    },
    issues
  }
}

export function registerAppIpcHandlers(options: RegisterAppIpcHandlersOptions): void {
  const {
    store,
    getMainWindow,
    applySettingsPatch,
    runtimeRequest,
    fetchUpstreamModels,
    prepareDeepseekBinary,
    resolveDeepseekConfigPath,
    terminalService,
    showTurnCompleteNotification,
    getAppVersion,
    resolveLogDirectory,
    logError
  } = options

  ipcMain.handle('settings:get', async () => store.load())
  ipcMain.handle('settings:set', async (_, partial: unknown) =>
    applySettingsPatch(
      parseIpcPayload('settings:set', settingsPatchSchema, partial) as AppSettingsPatch
    )
  )

  ipcMain.handle('asr:transcribe', async (_, payload: unknown) => {
    const request = parseIpcPayload('asr:transcribe', asrTranscribePayloadSchema, payload)
    const { config } = await readAsrConfigFile()
    const audio =
      request.audio instanceof ArrayBuffer
        ? Buffer.from(request.audio)
        : Buffer.from(request.audio.buffer, request.audio.byteOffset, request.audio.byteLength)
    return transcribeAudio({
      apiKey: config.apiKey,
      model: config.model,
      baseUrl: config.baseUrl,
      audio,
      mimeType: request.mimeType ?? 'audio/wav',
      fileName: request.fileName ?? 'recording.wav'
    })
  })

  ipcMain.handle('asr:config:read', async () => readAsrConfigFile())

  ipcMain.handle('asr:config:write', async (_, payload: unknown) => {
    const config = parseIpcPayload('asr:config:write', asrConfigPayloadSchema, payload)
    return writeAsrConfigFile(config)
  })

  ipcMain.handle('runtime:request', async (_, payload: unknown) => {
    const request = parseIpcPayload('runtime:request', runtimeRequestPayloadSchema, payload)
    return runtimeRequest(request.path, request.method, request.body)
  })

  ipcMain.handle('upstream:models', async () => fetchUpstreamModels())

  ipcMain.handle('deepseek:prepare-binary', async () => prepareDeepseekBinary())

  ipcMain.handle('workspace:pick-files', async (_, payload: unknown) => {
    const request = parseIpcPayload('workspace:pick-files', workspacePickFilesPayloadSchema, payload)
    const workspaceRoot = request.workspaceRoot ? expandHomePath(request.workspaceRoot) : ''
    const dialogDefaultPath =
      expandHomePath(request.defaultPath) || workspaceRoot || homedir()
    const imageExtensions = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'heic']
    const options: Electron.OpenDialogOptions = {
      title: 'Select attachments',
      defaultPath: dialogDefaultPath,
      properties: ['openFile', 'multiSelections', 'dontAddToRecent'],
      filters: [
        { name: 'All files', extensions: ['*'] },
        { name: 'Images', extensions: imageExtensions }
      ]
    }
    const mainWindow = getMainWindow()
    const result = mainWindow
      ? await dialog.showOpenDialog(mainWindow, options)
      : await dialog.showOpenDialog(options)
    if (result.canceled) {
      return { ok: true as const, paths: [] as const }
    }
    const resolvedRoot = workspaceRoot ? await canonicalPath(resolve(workspaceRoot)) : null
    const paths: string[] = []
    for (const picked of result.filePaths) {
      const abs = await canonicalPath(resolve(picked))
      if (resolvedRoot) {
        const rel = relative(resolvedRoot, abs)
        if (rel && !rel.startsWith('..') && !rel.startsWith('/')) {
          paths.push(rel.split('\\').join('/'))
          continue
        }
      }
      paths.push(abs.split('\\').join('/'))
    }
    return { ok: true as const, paths }
  })

  ipcMain.handle('workspace:pick-directory', async (_, defaultPath: unknown): Promise<WorkspacePickResult> => {
    const normalizedDefaultPath = parseIpcPayload(
      'workspace:pick-directory',
      z.object({ defaultPath: defaultPathSchema }).strict(),
      { defaultPath }
    ).defaultPath
    const options: Electron.OpenDialogOptions = {
      title: 'Select working directory',
      defaultPath: normalizedDefaultPath,
      properties: ['openDirectory', 'createDirectory', 'dontAddToRecent']
    }
    const mainWindow = getMainWindow()
    const result = mainWindow
      ? await dialog.showOpenDialog(mainWindow, options)
      : await dialog.showOpenDialog(options)
    return {
      canceled: result.canceled,
      path: result.canceled ? null : (result.filePaths[0] ?? null)
    }
  })

  ipcMain.handle('tui-sessions:list', async () => ({
    dir: defaultTuiSessionsDir(),
    sessions: await listTuiSessions()
  }))

  ipcMain.handle('tui-sessions:pick-file', async (_, defaultPath: unknown) => {
    const normalizedDefaultPath = parseIpcPayload(
      'tui-sessions:pick-file',
      z.object({ defaultPath: defaultPathSchema }).strict(),
      { defaultPath }
    ).defaultPath
    const options: Electron.OpenDialogOptions = {
      title: 'Select TUI session JSON',
      defaultPath: normalizedDefaultPath || defaultTuiSessionsDir(),
      properties: ['openFile', 'dontAddToRecent'],
      filters: [{ name: 'Session JSON', extensions: ['json'] }]
    }
    const mainWindow = getMainWindow()
    const result = mainWindow
      ? await dialog.showOpenDialog(mainWindow, options)
      : await dialog.showOpenDialog(options)
    return {
      canceled: result.canceled,
      path: result.canceled ? null : (result.filePaths[0] ?? null)
    }
  })

  ipcMain.handle(
    'skill:save-file',
    async (_, payload: unknown) => {
      const request = parseIpcPayload('skill:save-file', skillSaveFilePayloadSchema, payload)
      try {
        const rootPath = expandHomePath(request.rootPath)
        if (!rootPath) {
          return { ok: false as const, message: 'Skill directory is required.' }
        }
        const skillName = normalizeSkillFolderName(request.skillName)
        const skillDir = join(rootPath, skillName)
        const filePath = join(skillDir, 'SKILL.md')
        await mkdir(skillDir, { recursive: true })
        await writeFile(filePath, request.content, 'utf8')
        return { ok: true as const, path: filePath }
      } catch (error) {
        return {
          ok: false as const,
          message: error instanceof Error ? error.message : String(error)
        }
      }
    }
  )

  ipcMain.handle('skill:list-in-root', async (_, rootPath: unknown) => {
    const normalizedRootPath = parseIpcPayload('skill:list-in-root', rootPathSchema, rootPath)
    try {
      const target = expandHomePath(normalizedRootPath)
      if (!target) {
        return { ok: false as const, message: 'Skill directory is required.', skills: [] as const }
      }
      await mkdir(target, { recursive: true })
      const entries = await readdir(target, { withFileTypes: true })
      const skills: Array<{ id: string; name: string; path: string }> = []
      for (const entry of entries) {
        if (!entry.isDirectory()) continue
        const skillMd = join(target, entry.name, 'SKILL.md')
        try {
          await access(skillMd)
          skills.push({ id: entry.name, name: entry.name, path: skillMd })
        } catch {
          /* not a skill folder */
        }
      }
      skills.sort((a, b) => a.name.localeCompare(b.name))
      return { ok: true as const, skills }
    } catch (error) {
      return {
        ok: false as const,
        message: error instanceof Error ? error.message : String(error),
        skills: [] as const
      }
    }
  })

  ipcMain.handle('skill:open-root', async (_, rootPath: unknown) => {
    const normalizedRootPath = parseIpcPayload('skill:open-root', rootPathSchema, rootPath)
    try {
      const target = expandHomePath(normalizedRootPath)
      if (!target) {
        return { ok: false as const, message: 'Skill directory is required.' }
      }
      await mkdir(target, { recursive: true })
      return openPathWithShell(target)
    } catch (error) {
      return {
        ok: false as const,
        message: error instanceof Error ? error.message : String(error)
      }
    }
  })

  ipcMain.handle('deepseek:config:read', async () => {
    const path = resolveDeepseekConfigPath()
    try {
      const content = await readFile(path, 'utf8')
      return { path, content, exists: true as const }
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
        return { path, content: '', exists: false as const }
      }
      throw error
    }
  })

  ipcMain.handle('deepseek:config:write', async (_, content: unknown) => {
    const validatedContent = parseIpcPayload(
      'deepseek:config:write',
      deepseekConfigContentSchema,
      content
    )
    const path = resolveDeepseekConfigPath()
    await mkdir(dirname(path), { recursive: true })
    await writeFile(path, validatedContent, 'utf8')
    return { ok: true as const, path }
  })

  ipcMain.handle('deepseek:config:open-dir', async () => {
    try {
      const path = resolveDeepseekConfigPath()
      await mkdir(dirname(path), { recursive: true })
      try {
        await readFile(path, 'utf8')
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
          await writeFile(path, '', 'utf8')
        } else {
          throw error
        }
      }
      shell.showItemInFolder(path)
      return { ok: true as const, path }
    } catch (error) {
      return {
        ok: false as const,
        message: error instanceof Error ? error.message : String(error)
      }
    }
  })

  ipcMain.handle('feishu:config:read', async () => readFeishuConfigFile())

  ipcMain.handle('feishu:config:write', async (_, payload: unknown) => {
    const config = parseIpcPayload('feishu:config:write', feishuConfigPayloadSchema, payload)
    const { path } = await writeFeishuConfigFile(config)
    return { ok: true as const, path }
  })

  ipcMain.handle('wecom:config:read', async () => readWecomConfigFile())

  ipcMain.handle('wecom:config:write', async (_, payload: unknown) => {
    const config = parseIpcPayload('wecom:config:write', wecomConfigPayloadSchema, payload)
    const { path } = await writeWecomConfigFile(config)
    return { ok: true as const, path }
  })

  ipcMain.handle('feishu:config:open-dir', async () => {
    try {
      const path = resolveDeepseekConfigPath()
      await mkdir(dirname(path), { recursive: true })
      try {
        await readFile(path, 'utf8')
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
          await writeFeishuConfigFile({
            appId: '',
            appSecret: '',
            domain: 'feishu',
            chatId: ''
          })
        } else {
          throw error
        }
      }
      shell.showItemInFolder(path)
      return { ok: true as const, path }
    } catch (error) {
      return {
        ok: false as const,
        message: error instanceof Error ? error.message : String(error)
      }
    }
  })

  ipcMain.handle('feishu:register-start', async (event, payload: unknown) => {
    const request = parseIpcPayload(
      'feishu:register-start',
      feishuRegisterStartPayloadSchema,
      payload
    )
    const target: FeishuRegisterTarget = request.target ?? 'feishu'
    return runFeishuRegisterApp({ target, webContents: event.sender })
  })

  ipcMain.handle('feishu:register-cancel', async () => {
    cancelFeishuRegisterApp()
    return { ok: true as const }
  })

  ipcMain.handle('email:secret:status', async () => {
    const passwordEnv = await readEmailPasswordEnvKey()
    const passwordStatus = await resolveEmailPasswordStatus(passwordEnv)
    return {
      secureStorageAvailable: isEmailSecretStorageAvailable(),
      passwordEnv,
      ...passwordStatus
    }
  })

  ipcMain.handle('email:secret:set', async (_, payload: unknown) => {
    const { password } = parseIpcPayload('email:secret:set', emailSecretPayloadSchema, payload)
    await setEmailSmtpPassword(password)
    const settings = await store.load()
    await restartDeepseekChildIfRunning(settings)
    return { ok: true as const }
  })

  ipcMain.handle('email:secret:clear', async () => {
    await clearEmailSmtpPassword()
    return { ok: true as const }
  })

  ipcMain.handle('deepseek:paths:get', async () => resolveDeepseekPaths())

  ipcMain.handle('deepseek:hooks:open-dir', async () => {
    try {
      const hooksDir = resolveDeepseekPaths().hooksDir
      await mkdir(hooksDir, { recursive: true })
      return openPathWithShell(hooksDir)
    } catch (error) {
      return {
        ok: false as const,
        message: error instanceof Error ? error.message : String(error)
      }
    }
  })

  ipcMain.handle('endpoint:test', async (_event, args: {
    protocol: 'openai' | 'anthropic'
    baseUrl: string
    apiKey: string
    model: string
  }) => {
    const { protocol, baseUrl, apiKey, model } = args
    let url = baseUrl.replace(/\/+$/, '')
    if (protocol === 'anthropic') {
      if (url.endsWith('/v1/messages')) {
        // Full Messages URL supplied.
      } else if (url.endsWith('/v1')) {
        url = `${url}/messages`
      } else {
        url = `${url}/v1/messages`
      }
    } else if (/\/v\d+$/.test(url)) {
      url = `${url}/chat/completions`
    } else {
      url = `${url}/v1/chat/completions`
    }
    const start = Date.now()
    try {
      const controller = new AbortController()
      const timeout = setTimeout(() => controller.abort(), 15_000)
      const anthropic = protocol === 'anthropic'
      const toolName = 'compat_probe'
      let resp: Response
      try {
        resp = await fetch(url, {
          method: 'POST',
          headers: anthropic
            ? {
                'x-api-key': apiKey,
                'anthropic-version': '2023-06-01',
                'Content-Type': 'application/json'
              }
            : {
                'Authorization': `Bearer ${apiKey}`,
                'Content-Type': 'application/json'
              },
          body: JSON.stringify(anthropic
            ? {
                model,
                messages: [{ role: 'user', content: 'Call compat_probe with value ok.' }],
                max_tokens: 64,
                stream: false,
                tools: [{
                  name: toolName,
                  description: 'Compatibility probe',
                  input_schema: {
                    type: 'object',
                    properties: { value: { type: 'string' } },
                    required: ['value']
                  }
                }],
                tool_choice: { type: 'tool', name: toolName }
              }
            : {
                model,
                messages: [{ role: 'user', content: 'Call compat_probe with value ok.' }],
                max_tokens: 64,
                stream: false,
                tools: [{
                  type: 'function',
                  function: {
                    name: toolName,
                    description: 'Compatibility probe',
                    parameters: {
                      type: 'object',
                      properties: { value: { type: 'string' } },
                      required: ['value']
                    }
                  }
                }],
                tool_choice: { type: 'function', function: { name: toolName } }
              }),
          signal: controller.signal
        })
      } finally {
        clearTimeout(timeout)
      }
      const latencyMs = Date.now() - start
      if (resp.ok) {
        const body = await resp.json() as Record<string, unknown>
        const content = Array.isArray(body.content) ? body.content : []
        const choices = Array.isArray(body.choices) ? body.choices : []
        const anthropicToolOk = content.some((item) =>
          item && typeof item === 'object' &&
          (item as { type?: unknown }).type === 'tool_use' &&
          (item as { name?: unknown }).name === toolName
        )
        const firstChoice = choices[0] as {
          message?: { tool_calls?: Array<{ function?: { name?: string } }> }
        } | undefined
        const openAiToolOk = firstChoice?.message?.tool_calls?.some(
          (call) => call.function?.name === toolName
        ) === true
        if (!(anthropic ? anthropicToolOk : openAiToolOk)) {
          return {
            ok: false,
            model,
            latencyMs,
            message: '连接成功，但模型未返回必需的工具调用'
          }
        }
        const respModel = typeof body.model === 'string' ? body.model : model
        return {
          ok: true,
          model: respModel,
          latencyMs,
          message: `文本与工具协议兼容 (模型: ${respModel}, 延迟: ${latencyMs}ms)`
        }
      }
      const bodyText = (await resp.text()).slice(0, 200)
      return { ok: false, model, latencyMs, message: `HTTP ${resp.status}: ${bodyText}` }
    } catch (error) {
      const latencyMs = Date.now() - start
      const msg = error instanceof Error ? error.message : String(error)
      if (msg.includes('abort')) {
        return { ok: false, model, latencyMs, message: `连接超时 (15s)` }
      }
      return { ok: false, model, latencyMs, message: `连接失败: ${msg.slice(0, 100)}` }
    }
  })

  ipcMain.handle('deepseek:mcp:read', async () => {
    const path = resolveMcpConfigPath()
    try {
      const content = await readFile(path, 'utf8')
      return { path, content, exists: true as const }
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
        return {
          path,
          content: '{\n  "mcpServers": {}\n}\n',
          exists: false as const
        }
      }
      throw error
    }
  })

  ipcMain.handle('deepseek:mcp:write', async (_, content: unknown) => {
    const validatedContent = parseIpcPayload(
      'deepseek:mcp:write',
      deepseekConfigContentSchema,
      content
    )
    try {
      JSON.parse(validatedContent)
    } catch {
      throw new Error('MCP config must be valid JSON (see .deepseek/mcp.json format).')
    }
    const path = resolveMcpConfigPath()
    await mkdir(dirname(path), { recursive: true })
    await writeFile(path, validatedContent, 'utf8')
    return { ok: true as const, path }
  })

  ipcMain.handle('deepseek:mcp:open-dir', async () => {
    try {
      const home = resolveUserDeepseekDir()
      const mcpPath = resolveMcpConfigPath()
      await mkdir(home, { recursive: true })
      try {
        await readFile(mcpPath, 'utf8')
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
          await writeFile(mcpPath, '{\n  "mcpServers": {}\n}\n', 'utf8')
        } else {
          throw error
        }
      }
      shell.showItemInFolder(mcpPath)
      return { ok: true as const, path: mcpPath }
    } catch (error) {
      return {
        ok: false as const,
        message: error instanceof Error ? error.message : String(error)
      }
    }
  })

  // Settings UI calls this on mount so the token field shows the cached
  // fingerprint immediately, instead of "auto-managed" until the user clicks
  // Regenerate. Fingerprint is the same shape the regenerate IPC returns.
  ipcMain.handle('runtime:get-token-fingerprint', async () => {
    const settings = await store.load()
    const token = resolveEffectiveRuntimeToken(settings)
    return {
      fingerprint: token ? `${token.slice(0, 8)}…${token.slice(-4)}` : '',
      tokenPath: runtimeTokenFilePath()
    }
  })

  ipcMain.handle('deepseek:diagnostics', async () =>
    diagnoseDeepseekRuntime({ store, prepareDeepseekBinary, resolveDeepseekConfigPath })
  )

  ipcMain.handle('git:branches', async (_, workspaceRoot: unknown) =>
    getGitBranches(parseIpcPayload('git:branches', workspaceRootSchema, workspaceRoot))
  )
  ipcMain.handle('git:log', async (_, workspaceRoot: unknown) =>
    getGitLog(parseIpcPayload('git:log', workspaceRootSchema, workspaceRoot))
  )
  ipcMain.handle('git:working-changes', async (_, workspaceRoot: unknown) => {
    const root = parseIpcPayload('git:working-changes', workspaceRootSchema, workspaceRoot)
    const payload = await getGitWorkingChanges(root)
    // `not_git_repo` / `no_workspace` are expected, benign states (the folder
    // simply isn't a Git repo), not failures — logging them spams the log on
    // every poll. Only surface genuine Git failures.
    if (!payload.ok && payload.reason !== 'not_git_repo' && payload.reason !== 'no_workspace') {
      logError('git-working-changes', 'Failed to load Git working changes', {
        reason: payload.reason,
        message: payload.message,
        workspaceRoot: root
      })
    }
    return payload
  })
  ipcMain.handle(
    'git:switch-branch',
    async (_, payload: unknown) => {
      const request = parseIpcPayload('git:switch-branch', gitBranchPayloadSchema, payload)
      return switchGitBranch(request.workspaceRoot, request.branch)
    }
  )
  ipcMain.handle(
    'git:create-and-switch-branch',
    async (_, payload: unknown) => {
      const request = parseIpcPayload(
        'git:create-and-switch-branch',
        gitBranchPayloadSchema,
        payload
      )
      return createAndSwitchGitBranch(request.workspaceRoot, request.branch)
    }
  )
  ipcMain.handle('git:commit', async (_, payload: unknown) => {
    const request = parseIpcPayload('git:commit', gitCommitPayloadSchema, payload)
    const result = await commitGitChanges(request.workspaceRoot, request.message, request.paths)
    if (!result.ok) {
      logError('git-commit', 'Failed to commit Git changes', {
        reason: result.reason,
        message: result.message,
        workspaceRoot: request.workspaceRoot
      })
    }
    return result
  })
  ipcMain.handle('git:suggest-commit-message', async (_, payload: unknown) => {
    const request = parseIpcPayload('git:suggest-commit-message', gitCommitPathsPayloadSchema, payload)
    return suggestGitCommitMessage(request.workspaceRoot, request.paths)
  })

  ipcMain.handle('workspace:suggestions', async (_, workspaceRoot: unknown) =>
    getWorkspaceSuggestions(parseIpcPayload('workspace:suggestions', workspaceRootSchema, workspaceRoot))
  )

  ipcMain.handle('trending:repos', async (_, period: unknown) =>
    getTrendingRepos(parseIpcPayload('trending:repos', trendingPeriodSchema, period))
  )

  ipcMain.handle('editor:list', async () => listEditorsResult())
  ipcMain.handle('editor:open-path', async (_, payload: unknown) =>
    openEditorPath(parseIpcPayload('editor:open-path', openEditorPathPayloadSchema, payload))
  )

  ipcMain.handle('terminal:create', async (event, payload: unknown) =>
    terminalService.createTerminalSession(
      event.sender,
      parseIpcPayload('terminal:create', terminalCreateOptionsSchema, payload)
    )
  )
  ipcMain.handle('terminal:write', async (_, payload: unknown) =>
    terminalService.writeTerminalSession(
      parseIpcPayload('terminal:write', terminalInputPayloadSchema, payload)
    )
  )
  ipcMain.handle('terminal:resize', async (_, payload: unknown) =>
    terminalService.resizeTerminalSession(
      parseIpcPayload('terminal:resize', terminalResizePayloadSchema, payload)
    )
  )
  ipcMain.handle('terminal:close', async (_, payload: unknown) =>
    terminalService.closeTerminalSession(
      parseIpcPayload('terminal:close', terminalLifecyclePayloadSchema, payload)
    )
  )

  ipcMain.handle('file:resolve-workspace', async (_, payload: unknown) =>
    resolveWorkspaceFile(
      parseIpcPayload('file:resolve-workspace', workspaceFileTargetPayloadSchema, payload)
    )
  )
  ipcMain.handle('file:read-workspace', async (_, payload: unknown) =>
    readWorkspaceFile(
      parseIpcPayload('file:read-workspace', workspaceFileTargetPayloadSchema, payload)
    )
  )
  ipcMain.handle('file:write-workspace', async (_, payload: unknown) =>
    writeWorkspaceFile(
      parseIpcPayload('file:write-workspace', workspaceFileWritePayloadSchema, payload)
    )
  )
  ipcMain.handle('file:list-workspace', async (_, payload: unknown) => {
    const request = parseIpcPayload(
      'file:list-workspace',
      workspaceListDirectoryPayloadSchema,
      payload
    )
    return listWorkspaceDirectory(request.workspaceRoot, request.directoryPath ?? '')
  })

  ipcMain.handle('shell:open-external', async (_, url: unknown) => {
    const validatedUrl = parseIpcPayload('shell:open-external', shellOpenExternalUrlSchema, url)
    await shell.openExternal(validatedUrl)
  })
  ipcMain.handle('notification:turn-complete', async (_, payload: unknown) =>
    showTurnCompleteNotification(
      parseIpcPayload('notification:turn-complete', notificationPayloadSchema, payload)
    )
  )
  ipcMain.handle('app:version', async () => getAppVersion())

  ipcMain.handle('log:error', async (_, payload: unknown) => {
    const request = parseIpcPayload('log:error', logErrorPayloadSchema, payload)
    logError(request.category, request.message, request.detail)
  })
  ipcMain.handle('log:get-path', async () => resolveLogDirectory())
  ipcMain.handle('log:open-dir', async () => {
    const dir = resolveLogDirectory()
    try {
      await mkdir(dir, { recursive: true })
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      return { ok: false, message }
    }
    const error = await shell.openPath(dir)
    if (error) return { ok: false, message: error }
    return { ok: true }
  })

  ipcMain.handle('pet:fetch-manifest', async (_, force: unknown) =>
    fetchPetManifest(force === true)
  )
  ipcMain.handle('pet:resolve-spritesheet', async (_, payload: unknown) => {
    const request = parseIpcPayload(
      'pet:resolve-spritesheet',
      petResolveSpritesheetPayloadSchema,
      payload ?? {}
    )
    return resolvePetSpritesheet(request.slug)
  })
  ipcMain.handle('pet:cache-featured', async (_, limit: unknown) =>
    cacheFeaturedPets(typeof limit === 'number' ? limit : 15)
  )

  ipcMain.handle('usage:query', async (_, payload: unknown) => {
    const request = parseIpcPayload('usage:query', usageQueryPayloadSchema, payload ?? {})
    return usageLedgerService.query(request.range ?? '7d', request.locale ?? 'en')
  })
  ipcMain.handle('usage:prune-provider', async (_, payload: unknown) => {
    const request = parseIpcPayload(
      'usage:prune-provider',
      usagePruneProviderPayloadSchema,
      payload
    )
    await usageLedgerService.pruneProvider(request.providerId)
    return { ok: true as const }
  })
  ipcMain.handle('usage:prune-endpoint-model', async (_, payload: unknown) => {
    const request = parseIpcPayload(
      'usage:prune-endpoint-model',
      usagePruneEndpointModelPayloadSchema,
      payload
    )
    await usageLedgerService.pruneEndpointModel(request.providerId, request.modelId)
    return { ok: true as const }
  })
}
