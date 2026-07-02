import { app, BrowserWindow, dialog, ipcMain, nativeImage, Notification, session } from 'electron'
import { existsSync } from 'node:fs'
import { readFile } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { randomUUID } from 'node:crypto'
import { JsonSettingsStore, getRuntimeBaseUrl, devServerHintUrl } from './settings-store'
import deepseekLogoPng from '../asset/img/deepseek.png'
import {
  startDeepseekChild,
  stopDeepseekChild,
  stopDeepseekChildAndWait,
  waitForRuntimeHealth,
  isDeepseekChildRunning,
  reclaimDeepseekPort,
  inspectDeepseekLaunchConfig,
  resolveEffectiveRuntimeToken,
  readRuntimeTokenFile,
  clearRuntimeTokenFile,
  runtimeTokenFilePath,
  findAlternateDeepseekRuntimes,
  formatAlternateRuntimeHint
} from './deepseek-process'
import {
  resolveRuntimeLauncher,
  resolveRepoRoot,
  runtimeLauncherLabel,
  runtimeSpawnEnv
} from './resolve-python-runtime'
import {
  mergeAppearanceSettings,
  mergeClawSettings,
  normalizeAppSettings,
  type AppSettingsPatch,
  type AppSettingsV1
} from '../shared/app-settings'
import type { StartupPhase, StartupPhasePayload } from '../shared/ds-gui-api'
import { isAllowedDevPreviewUrl } from '../shared/dev-preview-url'
import { fetchUpstreamModelIds } from './upstream-models'
import {
  deepseekTuiConfigChanged,
  resolveDeepseekConfigPath,
  syncDeepseekTuiConfig
} from './deepseek-config'
import { configureLogger, logError, logWarn, pruneOnStartup } from './logger'
import { createRuntimeReadyCache } from './runtime-ready-cache'
import { sseStartPayloadSchema, streamIdSchema } from './ipc/app-ipc-schemas'
import { createTerminalService } from './services/terminal-service'
import { registerAppIpcHandlers } from './ipc/register-app-ipc-handlers'

const mainDir = import.meta.dirname
const APP_USER_MODEL_ID = 'com.deepseek.workbench'
const MANAGED_RUNTIME_STARTUP_TIMEOUT_MS = 180_000

// Ensure Python spawn helpers can find the monorepo checkout in dev.
const detectedRepoRoot = resolveRepoRoot()
if (detectedRepoRoot && !process.env.DEEPSEEK_REPO_ROOT) {
  process.env.DEEPSEEK_REPO_ROOT = detectedRepoRoot
}
Object.assign(process.env, runtimeSpawnEnv())
const startupTraceEnabled = process.env.DEEPSEEK_GUI_STARTUP_TRACE === '1'
const startupTraceStart = Date.now()
let currentStartupPhase: StartupPhasePayload | null = null

function traceStartup(label: string, detail?: unknown): void {
  if (!startupTraceEnabled) return
  const elapsed = String(Date.now() - startupTraceStart).padStart(6, ' ')
  if (detail === undefined) {
    console.info(`[startup +${elapsed}ms] ${label}`)
  } else {
    console.info(`[startup +${elapsed}ms] ${label}`, detail)
  }
}

function emitStartupPhase(phase: StartupPhase, detail?: string): void {
  currentStartupPhase = {
    phase,
    at: Date.now(),
    ...(detail ? { detail } : {})
  }
  traceStartup(`phase:${phase}`, detail)
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('startup:phase', currentStartupPhase)
  }
}

traceStartup('main module evaluated')

// TEMP(scroll-jank diagnostics): remote debugging port for live GPU trace. Remove after.
if (process.env.ELECTRON_RENDERER_URL) {
  app.commandLine.appendSwitch('remote-debugging-port', '9222')
}

if (process.platform === 'win32') {
  app.setAppUserModelId(APP_USER_MODEL_ID)
}

let mainWindow: BrowserWindow | null = null
let store: JsonSettingsStore
let logDir = ''
const terminalService = createTerminalService()

function resolveLogDirectory(): string {
  return join(app.getPath('userData'), 'logs')
}

function resolvePreloadPath(): string {
  const cjsPath = join(mainDir, '../preload/index.cjs')
  if (existsSync(cjsPath)) return cjsPath
  return join(mainDir, '../preload/index.mjs')
}

function installDevPreviewWebviewGuards(): void {
  app.on('web-contents-created', (_, contents) => {
    contents.on('will-attach-webview', (event, webPreferences, params) => {
      const src = typeof params.src === 'string' ? params.src : ''
      if (!isAllowedDevPreviewUrl(src)) {
        event.preventDefault()
        return
      }

      delete webPreferences.preload
      delete (webPreferences as { preloadURL?: string }).preloadURL
      webPreferences.nodeIntegration = false
      webPreferences.contextIsolation = true
      webPreferences.sandbox = true
      webPreferences.webSecurity = true
      webPreferences.allowRunningInsecureContent = false
    })

    contents.on('will-navigate', (event, navigationUrl) => {
      if (contents.getType() !== 'webview') return
      if (!isAllowedDevPreviewUrl(navigationUrl)) event.preventDefault()
    })

    contents.setWindowOpenHandler(({ url }) => {
      if (contents.getType() !== 'webview') return { action: 'allow' }
      return isAllowedDevPreviewUrl(url) ? { action: 'allow' } : { action: 'deny' }
    })
  })
}

function installMediaPermissionHandler(): void {
  // Voice input calls getUserMedia({ audio: true }). macOS gates the microphone
  // behind the audio-input entitlement + NSMicrophoneUsageDescription (see
  // electron-builder.config.cjs); Electron also routes the `media` permission
  // through this handler. Grant requests explicitly so mic capture works
  // regardless of Electron's default, while keeping all other permission
  // requests at their previous (granted) behavior.
  session.defaultSession.setPermissionRequestHandler((_webContents, _permission, callback) => {
    callback(true)
  })
}

type SseControllerState = {
  controller: AbortController
  stoppedByClient: boolean
}

type TurnCompleteNotificationPayload = {
  threadId?: string
  title?: string
  body?: string
}

const sseControllers = new Map<string, SseControllerState>()

function createAppIcon(source: string): Electron.NativeImage {
  return source.startsWith('data:')
    ? nativeImage.createFromDataURL(source)
    : nativeImage.createFromPath(source)
}

function resolveDevIconPath(): string {
  const fromSource = join(dirname(fileURLToPath(import.meta.url)), '../asset/img/deepseek.png')
  if (existsSync(fromSource)) return fromSource
  return join(process.cwd(), 'src/asset/img/deepseek.png')
}
const devIconPath = resolveDevIconPath()
const appIcon = app.isPackaged
  ? createAppIcon(deepseekLogoPng)
  : nativeImage.createFromPath(devIconPath)
traceStartup('app icon loaded', {
  source: app.isPackaged ? (deepseekLogoPng.startsWith('data:') ? 'data-url' : 'path') : devIconPath,
  empty: appIcon.isEmpty(),
  size: appIcon.isEmpty() ? undefined : appIcon.getSize()
})
const gotSingleInstanceLock = app.requestSingleInstanceLock()
traceStartup('single instance lock checked', { gotSingleInstanceLock })

function normalizeNotificationText(raw: string | undefined, fallback: string, maxLength: number): string {
  const value = typeof raw === 'string' && raw.trim() ? raw.trim() : fallback
  return value.length > maxLength ? `${value.slice(0, maxLength - 1)}…` : value
}

function revealMainWindow(): void {
  if (!mainWindow) {
    createWindow()
  }
  if (!mainWindow) return
  if (mainWindow.isMinimized()) mainWindow.restore()
  mainWindow.show()
  mainWindow.focus()
}

async function showTurnCompleteNotification(
  payload: TurnCompleteNotificationPayload
): Promise<{ ok: true; shown: boolean; reason?: string } | { ok: false; message: string }> {
  const settings = await store.load()
  if (!settings.notifications.turnComplete) {
    return { ok: true, shown: false, reason: 'disabled' }
  }
  if (!Notification.isSupported()) {
    return { ok: true, shown: false, reason: 'unsupported' }
  }

  const title = normalizeNotificationText(payload.title, 'DeepSeek GUI', 80)
  const body = normalizeNotificationText(payload.body, 'Conversation complete.', 180)

  try {
    const notification = new Notification({
      title,
      body,
      icon: appIcon.isEmpty() ? undefined : appIcon
    })
    notification.on('click', () => {
      revealMainWindow()
    })
    notification.show()
    return { ok: true, shown: true }
  } catch (e) {
    const message = e instanceof Error ? e.message : String(e)
    logError('notification', 'Failed to show turn completion notification', {
      message,
      threadId: payload.threadId
    })
    return { ok: false, message }
  }
}

if (!gotSingleInstanceLock) {
  app.quit()
}

function runtimeFailure(error: string, message: string, status = 0) {
  return {
    ok: false as const,
    status,
    body: JSON.stringify({ error, message })
  }
}

function resolveConfiguredApiKey(settings: AppSettingsV1): string {
  const fromSettings = settings.deepseek.apiKey?.trim() ?? ''
  const fromEnv = process.env.DEEPSEEK_API_KEY?.trim() ?? ''
  const fromCustom = settings.customEndpoints.find(
    (endpoint) => endpoint.enabled && endpoint.apiKey.trim()
  )?.apiKey.trim() ?? ''
  return fromSettings || fromEnv || fromCustom
}

function runtimeJsonError(error: string, message: string): Error {
  return new Error(JSON.stringify({ error, message }))
}

function parseRuntimeErrorBody(body: string): { error?: string; message: string } {
  const fallback = body.trim() || 'The local runtime returned an unexpected error.'
  try {
    const parsed = JSON.parse(body) as {
      error?: string | { message?: string; status?: number }
      message?: string
    }
    const nested =
      parsed.error && typeof parsed.error === 'object' ? parsed.error.message?.trim() ?? '' : ''
    const topLevel =
      typeof parsed.error === 'string' && parsed.error.trim() ? parsed.error.trim() : undefined
    const message =
      typeof parsed.message === 'string' && parsed.message.trim()
        ? parsed.message.trim()
        : nested || topLevel || fallback
    return { ...(topLevel ? { error: topLevel } : {}), message }
  } catch {
    return { message: fallback }
  }
}

async function probeThreadApi(settings: AppSettingsV1): Promise<
  | { ok: true }
  | { ok: false; error: string; message: string }
> {
  const base = getRuntimeBaseUrl(settings.deepseek.port)
  const headers = new Headers({ Accept: 'application/json' })
  const runtimeToken = resolveEffectiveRuntimeToken(settings)
  if (runtimeToken) {
    headers.set('Authorization', `Bearer ${runtimeToken}`)
  }

  try {
    const res = await fetch(`${base}/v1/threads?limit=1`, {
      headers,
      signal: AbortSignal.timeout(2_000)
    })
    if (res.ok) return { ok: true }
    const info = parseRuntimeErrorBody(await res.text())
    if (res.status === 401 && /bearer token required/i.test(info.message)) {
      return {
        ok: false,
        error: 'runtime_auth_required',
        message: 'The local runtime requires a bearer token for thread APIs.'
      }
    }
    return {
      ok: false,
      error: info.error ?? 'runtime_request_failed',
      message: info.message
    }
  } catch (e) {
    return {
      ok: false,
      error: 'fetch_failed',
      message: e instanceof Error ? e.message : String(e)
    }
  }
}

function parseSseData(raw: string): unknown | null {
  const lines = raw.split('\n')
  const dataLines: string[] = []
  for (const line of lines) {
    const normalized = line.endsWith('\r') ? line.slice(0, -1) : line
    if (normalized.startsWith('data:')) {
      dataLines.push(normalized.slice(5).trimStart())
    }
  }
  if (!dataLines.length) return null
  const payload = dataLines.join('\n')
  try {
    return JSON.parse(payload)
  } catch {
    return null
  }
}

function takeSseBlock(buffer: string): { block: string; rest: string } | null {
  const lf = buffer.indexOf('\n\n')
  const crlf = buffer.indexOf('\r\n\r\n')
  if (lf === -1 && crlf === -1) return null
  if (crlf !== -1 && (lf === -1 || crlf < lf)) {
    return {
      block: buffer.slice(0, crlf),
      rest: buffer.slice(crlf + 4)
    }
  }
  return {
    block: buffer.slice(0, lf),
    rest: buffer.slice(lf + 2)
  }
}

/** Avoid UnhandledPromiseRejection when renderer reloads or window closes mid-SSE. */
function safeWebContentsSend(
  wc: Electron.WebContents,
  channel: string,
  payload: unknown
): boolean {
  if (wc.isDestroyed()) return false
  try {
    wc.send(channel, payload)
    return true
  } catch {
    return false
  }
}

function abortAllSseStreams(): void {
  for (const state of sseControllers.values()) {
    state.stoppedByClient = true
    state.controller.abort()
  }
  sseControllers.clear()
}

let runtimeEnsurePromise: Promise<void> | null = null
let runtimeSettingsApplyPromise: Promise<void> | null = null

const runtimeReadyCache = createRuntimeReadyCache({
  onTrace: (event, reason) => traceStartup(`runtime-ready:${event}${reason ? ` ${reason}` : ''}`)
})
function invalidateRuntimeReady(reason: string): void {
  runtimeReadyCache.invalidate(reason)
}

function queueRuntimeSettingsApply(prev: AppSettingsV1, next: AppSettingsV1): void {
  if (!deepseekTuiConfigChanged(prev, next) && !runtimeStartupConfigChanged(prev, next)) {
    return
  }

  invalidateRuntimeReady('settings-apply:queued')
  const previousTask = runtimeSettingsApplyPromise ?? Promise.resolve()
  const task = previousTask
    .catch(() => undefined)
    .then(async () => {
      if (deepseekTuiConfigChanged(prev, next)) {
        await syncDeepseekTuiConfig(next, prev)
      }
      await restartManagedRuntimeForSettingsChange(prev, next)
    })
    .catch((error: unknown) => {
      logWarn('settings-apply', 'Failed to apply DeepSeek runtime settings in background', {
        message: error instanceof Error ? error.message : String(error)
      })
    })
    .finally(() => {
      if (runtimeSettingsApplyPromise === task) {
        runtimeSettingsApplyPromise = null
      }
    })

  runtimeSettingsApplyPromise = task
}

async function waitForQueuedRuntimeSettingsApply(): Promise<void> {
  if (!runtimeSettingsApplyPromise) return
  await runtimeSettingsApplyPromise
}

async function ensureRuntime(settings: AppSettingsV1): Promise<void> {
  if (runtimeEnsurePromise) return runtimeEnsurePromise
  if (
    !runtimeSettingsApplyPromise &&
    (!settings.deepseek.autoStart || isDeepseekChildRunning()) &&
    runtimeReadyCache.isFresh()
  ) {
    return
  }
  runtimeEnsurePromise = ensureRuntimeOnce(settings)
    .catch((error) => {
      emitStartupPhase(
        'offline',
        error instanceof Error ? error.message : String(error)
      )
      throw error
    })
    .finally(() => {
      runtimeEnsurePromise = null
    })
  return runtimeEnsurePromise
}

async function runtimeOfflineMessage(settings: AppSettingsV1): Promise<string> {
  const alternates = await findAlternateDeepseekRuntimes(settings.deepseek.port)
  const hint = formatAlternateRuntimeHint(alternates, settings.deepseek.port)
  if (hint) return hint
  return 'The local runtime is offline. Enable automatic startup in Settings, or start `deepseek serve --http` manually.'
}

async function ensureRuntimeOnce(settings: AppSettingsV1): Promise<void> {
  await waitForQueuedRuntimeSettingsApply()

  const hasApiKey = Boolean(resolveConfiguredApiKey(settings))
  const runtimeToken = settings.deepseek.runtimeToken?.trim() ?? ''
  emitStartupPhase('runtime-check')
  const healthy = await waitForRuntimeHealth(settings.deepseek.port, 2000)

  if (healthy) {
    emitStartupPhase('thread-api')
    const threadApi = await probeThreadApi(settings)
    if (threadApi.ok) {
      if (!isDeepseekChildRunning() && settings.deepseek.autoStart && hasApiKey) {
        const launch = await inspectDeepseekLaunchConfig(settings)
        if (launch.state === 'deepseek' && !launch.matches) {
          console.warn(
            `[deepseek-gui] restarting runtime on port ${settings.deepseek.port}; launch config mismatch: ${launch.reason}`
          )
          abortAllSseStreams()
          const reclaimed = await reclaimDeepseekPort(settings.deepseek.port)
          if (!reclaimed.ok) {
            throw runtimeJsonError('runtime_port_conflict', reclaimed.message)
          }
        } else {
          emitStartupPhase('runtime-ready')
          runtimeReadyCache.markReady()
          return
        }
      } else {
        emitStartupPhase('runtime-ready')
        runtimeReadyCache.markReady()
        return
      }
    }

    if (!threadApi.ok) {
      const canReclaimConflictingRuntime =
        threadApi.error === 'runtime_auth_required' &&
        !runtimeToken &&
        settings.deepseek.autoStart &&
        hasApiKey

      if (!canReclaimConflictingRuntime) {
        throw runtimeJsonError(threadApi.error, threadApi.message)
      }

      abortAllSseStreams()
      const reclaimed = await reclaimDeepseekPort(settings.deepseek.port)
      if (!reclaimed.ok) {
        throw runtimeJsonError('runtime_port_conflict', reclaimed.message)
      }
    }
  } else {
    if (!hasApiKey) {
      throw runtimeJsonError(
        'missing_api_key',
        'Configure a DeepSeek or custom-provider API key before starting the local runtime.'
      )
    }
    if (!settings.deepseek.autoStart) {
      throw runtimeJsonError('runtime_offline', await runtimeOfflineMessage(settings))
    }
  }

  if (!hasApiKey) {
    throw runtimeJsonError(
      'missing_api_key',
      'Configure a DeepSeek or custom-provider API key before starting the local runtime.'
    )
  }
  if (!settings.deepseek.autoStart) {
    throw runtimeJsonError('runtime_offline', await runtimeOfflineMessage(settings))
  }
  emitStartupPhase('runtime-config-sync')
  await syncDeepseekTuiConfig(settings)
  try {
    emitStartupPhase(
      'runtime-spawn',
      'Starting the local Python runtime. Dev launches can take 15-25s.'
    )
    await startDeepseekChild(settings)
  } catch (e) {
    console.error('[deepseek-gui] failed to start deepseek:', e)
    throw e
  }
  emitStartupPhase('runtime-health')
  const started = await waitForRuntimeHealth(
    settings.deepseek.port,
    MANAGED_RUNTIME_STARTUP_TIMEOUT_MS
  )
  if (!started) {
    throw runtimeJsonError(
      'runtime_unhealthy',
      'The local runtime did not become healthy after launch.'
    )
  }

  emitStartupPhase('thread-api')
  const threadApi = await probeThreadApi(settings)
  if (!threadApi.ok) {
    throw runtimeJsonError(threadApi.error, threadApi.message)
  }
  emitStartupPhase('runtime-ready')
  runtimeReadyCache.markReady()
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function waitForDevRenderer(url: string, timeoutMs = 60_000): Promise<boolean> {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    try {
      const res = await fetch(url, { method: 'GET' })
      if (res.ok) return true
    } catch {
      /* Vite not ready yet */
    }
    await sleep(300)
  }
  return false
}

function createWindow(): void {
  traceStartup('createWindow:start')
  const preloadPath = resolvePreloadPath()
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 840,
    minWidth: 960,
    minHeight: 640,
    icon: appIcon.isEmpty() ? undefined : appIcon,
    titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'default',
    trafficLightPosition: process.platform === 'darwin' ? { x: 16, y: 14 } : undefined,
    show: false,
    webPreferences: {
      preload: preloadPath,
      contextIsolation: true,
      sandbox: true,
      webviewTag: true
    }
  })
  mainWindow.webContents.on('preload-error', (_event, preloadPath, error) => {
    const message = error instanceof Error ? error.message : String(error)
    console.error(`[deepseek-gui] failed to load preload ${preloadPath}:`, error)
    logError('preload', 'Failed to load preload script', { preloadPath, message })
  })
  mainWindow.webContents.on('console-message', (_event, level, message, line, sourceId) => {
    const tag = level === 'error' ? '[renderer-error]' : `[renderer-log:${level}]`
    console.log(`${tag} ${message} (${sourceId}:${line})`)
  })
  mainWindow.webContents.on('render-process-gone', (_event, details) => {
    console.error('[deepseek-gui] render-process-gone:', details)
  })
  const showWindow = (): void => {
    if (!mainWindow || mainWindow.isDestroyed() || mainWindow.isVisible()) return
    mainWindow.show()
  }
  mainWindow.on('closed', () => {
    abortAllSseStreams()
    terminalService.disposeTerminalSessionsForWindow(mainWindow?.id ?? -1)
    mainWindow = null
  })
  mainWindow.webContents.on('did-start-navigation', (_event, _url, _inPlace, isMainFrame) => {
    if (isMainFrame && mainWindow) {
      abortAllSseStreams()
      terminalService.disposeTerminalSessionsForWindow(mainWindow.id)
    }
  })
  const devUrl = devServerHintUrl(app.isPackaged)
  traceStartup('createWindow:load', { devUrl: devUrl ?? 'file' })
  emitStartupPhase('renderer-loading')

  const loadRenderer = async (): Promise<void> => {
    if (!mainWindow || mainWindow.isDestroyed()) return
    if (devUrl) {
      const ready = await waitForDevRenderer(devUrl)
      if (!ready) {
        dialog.showErrorBox(
          'DeepSeek Workbench dev server',
          `Could not reach the Vite dev server at ${devUrl}.\n\n` +
            'Ensure port 5173 is free, then run ./scripts/dev-workbench.sh again.\n' +
            'Do not open the runtime API port (7878) in a browser — that is not the GUI.'
        )
        return
      }
      await mainWindow.loadURL(devUrl)
      return
    }
    await mainWindow.loadFile(join(mainDir, '../renderer/index.html'))
  }

  void loadRenderer().catch((error) => {
    const message = error instanceof Error ? error.message : String(error)
    console.error('[workbench] failed to load renderer:', error)
    dialog.showErrorBox('DeepSeek Workbench failed to load UI', message)
  })

  mainWindow.webContents.on('did-fail-load', (_event, code, description, validatedURL) => {
    if (!mainWindow || !devUrl) return
    if (validatedURL.startsWith(devUrl)) {
      console.error('[workbench] renderer load failed:', code, description, validatedURL)
      dialog.showErrorBox(
        'DeepSeek Workbench UI failed to load',
        `${description} (${code})\n${validatedURL}\n\n` +
          'If you opened http://127.0.0.1:7878 in a browser, that is the API — use the Electron window instead.'
      )
    }
  })

  mainWindow.once('ready-to-show', () => {
    traceStartup('window:ready-to-show')
    showWindow()
  })
  mainWindow.webContents.once('did-finish-load', () => {
    traceStartup('window:did-finish-load')
    showWindow()
  })
  setTimeout(() => {
    traceStartup('window:fallback-show-timeout')
    showWindow()
  }, 1500)
}

function deepseekLaunchConfigChanged(prev: AppSettingsV1, next: AppSettingsV1): boolean {
  const a = prev.deepseek
  const b = next.deepseek
  return (
    a.binaryPath !== b.binaryPath ||
    a.port !== b.port ||
    a.autoStart !== b.autoStart ||
    a.apiKey !== b.apiKey ||
    a.baseUrl !== b.baseUrl ||
    a.runtimeToken !== b.runtimeToken ||
    a.approvalPolicy !== b.approvalPolicy ||
    a.sandboxMode !== b.sandboxMode ||
    JSON.stringify(prev.customEndpoints) !== JSON.stringify(next.customEndpoints) ||
    JSON.stringify(a.extraCorsOrigins) !== JSON.stringify(b.extraCorsOrigins)
  )
}

function runtimeStartupConfigChanged(prev: AppSettingsV1, next: AppSettingsV1): boolean {
  return deepseekLaunchConfigChanged(prev, next)
}

async function restartManagedRuntimeForSettingsChange(
  prev: AppSettingsV1,
  next: AppSettingsV1
): Promise<void> {
  if (!runtimeStartupConfigChanged(prev, next)) return

  abortAllSseStreams()

  // Even when the child isn't ours (e.g., reclaimed external runtime), a
  // settings-driven config change must reclaim the port so the new spawn
  // picks up the latest token / approval policy / sandbox / base url.
  const samePort = prev.deepseek.port === next.deepseek.port
  if (isDeepseekChildRunning()) {
    await stopDeepseekChildAndWait()
  }

  if (samePort) {
    const reclaimed = await reclaimDeepseekPort(prev.deepseek.port)
    if (!reclaimed.ok) {
      console.warn('[deepseek-gui] runtime restart skipped:', reclaimed.message)
      return
    }
  }

  if (!resolveConfiguredApiKey(next) || !next.deepseek.autoStart) {
    return
  }

  try {
    await startDeepseekChild(next)
    const healthy = await waitForRuntimeHealth(
      next.deepseek.port,
      MANAGED_RUNTIME_STARTUP_TIMEOUT_MS
    )
    if (!healthy) {
      console.warn('[deepseek-gui] runtime restart did not become healthy after settings change')
    }
  } catch (e) {
    console.warn('[deepseek-gui] runtime restart failed after settings change:', e)
  }
}

async function runtimeRequest(
  settings: AppSettingsV1,
  pathAndQuery: string,
  init: { method?: string; body?: string; headers?: Record<string, string> }
): Promise<{ ok: boolean; status: number; body: string }> {
  try {
    await ensureRuntime(settings)
    const base = getRuntimeBaseUrl(settings.deepseek.port)
    const pathNorm = pathAndQuery.startsWith('/') ? pathAndQuery : `/${pathAndQuery}`
    const url = `${base}${pathNorm}`
    const hdrs = new Headers(init.headers ?? {})
    hdrs.set('Accept', 'application/json')
    let requestBody = init.body
    const isStartTurn =
      (init.method ?? 'GET') === 'POST' &&
      /\/v1\/threads\/[^/]+\/turns$/.test(pathNorm.split('?')[0] ?? pathNorm)
    const mainRequestStartMs = Date.now()
    if (isStartTurn && requestBody) {
      try {
        const payload = JSON.parse(requestBody) as Record<string, unknown>
        if (payload.main_runtime_request_start_ms == null) {
          payload.main_runtime_request_start_ms = mainRequestStartMs
        }
        requestBody = JSON.stringify(payload)
      } catch {
        /* keep original body */
      }
    }
    if (init.body && !hdrs.has('Content-Type')) {
      hdrs.set('Content-Type', 'application/json')
    }
    const effectiveToken = resolveEffectiveRuntimeToken(settings)
    if (effectiveToken) {
      hdrs.set('Authorization', `Bearer ${effectiveToken}`)
    }
    const res = await fetch(url, {
      method: init.method ?? 'GET',
      headers: hdrs,
      body: requestBody,
      signal: AbortSignal.timeout(init.method === 'POST' ? 60_000 : 15_000)
    })
    const text = await res.text()
    if (isStartTurn) {
      console.info(
        `[deepseek-gui] turn_request path=${pathNorm} status=${res.status} elapsed_ms=${Date.now() - mainRequestStartMs}`
      )
    }
    if (res.status === 401 || res.status === 503) {
      invalidateRuntimeReady(`runtime-request:${res.status}`)
    }
    return { ok: res.ok, status: res.status, body: text }
  } catch (e) {
    const message = e instanceof Error ? e.message : String(e)
    const isAbort = e instanceof Error && (e.name === 'AbortError' || e.name === 'TimeoutError')
    // Synthesize HTTP-like status codes so callers can branch on connectivity
    // class without parsing free-form messages: 408 = local timeout (abort),
    // 503 = connection refused / unreachable, 0 = unknown.
    const status = isAbort ? 408 : 503
    invalidateRuntimeReady(`runtime-request:${status}`)
    logError('runtime-request', `HTTP request to ${pathAndQuery} failed`, { message, status })
    try {
      const parsed = JSON.parse(message) as { error?: string; message?: string }
      if (parsed.error || parsed.message) {
        return runtimeFailure(
          parsed.error ?? 'runtime_request_failed',
          parsed.message ?? message,
          status
        )
      }
    } catch {
      /* use generic fallback below */
    }
    return runtimeFailure(isAbort ? 'request_timeout' : 'fetch_failed', message, status)
  }
}

app.whenReady().then(async () => {
  traceStartup('app.whenReady:start')
  emitStartupPhase('app-ready')
  if (!gotSingleInstanceLock) return

  traceStartup('install webview guards:start')
  installDevPreviewWebviewGuards()
  installMediaPermissionHandler()
  traceStartup('install webview guards:done')

  if (process.platform === 'darwin' && !appIcon.isEmpty()) {
    app.dock.setIcon(appIcon)
  }

  store = new JsonSettingsStore(app.getPath('userData'))
  traceStartup('settings load:start')
  emitStartupPhase('settings')
  let initial = await store.load()
  traceStartup('settings load:done')

  // Backfill apiKey from config.toml so user edits to config.toml take effect.
  // The GUI's deepseek-gui-settings.json may hold a stale key; config.toml is
  // the source of truth for api_key.
  try {
    const tomlContent = await readFile(resolveDeepseekConfigPath(), 'utf8')
    const match = tomlContent.match(/^\s*api_key\s*=\s*"([^"]*)"/m)
    const tomlKey = match?.[1]?.trim() ?? ''
    if (tomlKey && tomlKey !== initial.deepseek.apiKey) {
      initial = await store.patch({ deepseek: { apiKey: tomlKey } })
      traceStartup('apiKey backfilled from config.toml')
    }
  } catch { /* config.toml missing or unreadable — use GUI value */ }

  logDir = resolveLogDirectory()
  configureLogger({
    dir: logDir,
    enabled: initial.log.enabled,
    retentionDays: initial.log.retentionDays
  })
  traceStartup('logger configured')

  traceStartup('ipc registration:start')
  const applySettingsPatch = async (partial: AppSettingsPatch): Promise<AppSettingsV1> => {
    const prev = await store.load()
    const next = normalizeAppSettings({
      ...prev,
      ...partial,
      deepseek: { ...prev.deepseek, ...(partial.deepseek ?? {}) },
      log: { ...prev.log, ...(partial.log ?? {}) },
      notifications: { ...prev.notifications, ...(partial.notifications ?? {}) },
      skills: { ...prev.skills, ...(partial.skills ?? {}) },
      claw: mergeClawSettings(prev.claw, partial.claw),
      guiUpdate: { ...prev.guiUpdate, ...(partial.guiUpdate ?? {}) },
      appearance: mergeAppearanceSettings(prev.appearance, partial.appearance),
      agentProvider: 'deepseek-runtime'
    })
    if (prev.log.enabled !== next.log.enabled || prev.log.retentionDays !== next.log.retentionDays) {
      configureLogger({ enabled: next.log.enabled, retentionDays: next.log.retentionDays })
    }
    const saved = await store.patch(partial)
    queueRuntimeSettingsApply(prev, saved)
    return saved
  }

  const fetchModels = async () => {
    const settings = await store.load()
    const key = resolveConfiguredApiKey(settings)
    return fetchUpstreamModelIds(settings, key)
  }

  const prepareDeepseekBinary = async () => {
    const settings = await store.load()
    try {
      const launcher = resolveRuntimeLauncher(settings.deepseek.binaryPath)
      return { ok: true as const, path: runtimeLauncherLabel(launcher) }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      logError('deepseek-binary', 'Failed to resolve Python runtime launcher', { message })
      return {
        ok: false as const,
        message
      }
    }
  }

  registerAppIpcHandlers({
    store,
    getMainWindow: () => mainWindow,
    applySettingsPatch,
    runtimeRequest: async (path, method, body) => {
      const settings = await store.load()
      return runtimeRequest(settings, path, { method, body })
    },
    fetchUpstreamModels: fetchModels,
    prepareDeepseekBinary,
    resolveDeepseekConfigPath,
    terminalService,
    showTurnCompleteNotification,
    getAppVersion: () => app.getVersion(),
    resolveLogDirectory,
    logError
  })
  ipcMain.handle('startup:phase:get', async () => currentStartupPhase)

  ipcMain.handle('deepseek:spawn-if-needed', async () => {
    const s = await store.load()
    if (!resolveConfiguredApiKey(s)) {
      return {
        started: false,
        healthy: false,
        error: 'missing_api_key',
        message: 'DeepSeek API Key is required before starting the local runtime.'
      }
    }
    try {
      await ensureRuntime(s)
    } catch (e) {
      console.error('[deepseek-gui] spawn:', e)
      logError('deepseek-spawn', 'Failed to start deepseek runtime', { message: e instanceof Error ? e.message : String(e) })
      return {
        started: false,
        healthy: false,
        error: 'spawn_failed',
        message: e instanceof Error ? e.message : String(e)
      }
    }
    const ok = await waitForRuntimeHealth(
      s.deepseek.port,
      MANAGED_RUNTIME_STARTUP_TIMEOUT_MS
    )
    return { started: true, healthy: ok, pid: isDeepseekChildRunning() }
  })

  ipcMain.handle('runtime:sse:start', async (event, args: unknown) => {
    const request = sseStartPayloadSchema.parse(args)
    const s = await store.load()
    await ensureRuntime(s)
    const requestedId = request.streamId?.trim() ?? ''
    const id = requestedId || randomUUID()
    const existing = sseControllers.get(id)
    if (existing) {
      existing.stoppedByClient = true
      existing.controller.abort()
      sseControllers.delete(id)
    }
    const ac = new AbortController()
    const state: SseControllerState = { controller: ac, stoppedByClient: false }
    sseControllers.set(id, state)
    const base = getRuntimeBaseUrl(s.deepseek.port)
    const token = resolveEffectiveRuntimeToken(s)
    const url = `${base}/v1/threads/${encodeURIComponent(request.threadId)}/events?since_seq=${request.sinceSeq}`

    ;(async () => {
      const wc = event.sender
      const headers: Record<string, string> = { Accept: 'text/event-stream' }
      if (token) headers.Authorization = `Bearer ${token}`
      const stopStream = (): void => {
        state.stoppedByClient = true
        ac.abort()
      }
      try {
        const res = await fetch(url, { signal: ac.signal, headers })
        if (!res.ok || !res.body) {
          safeWebContentsSend(wc, 'runtime:sse-error', { streamId: id, status: res.status })
          logError('sse', `SSE connection failed for thread ${request.threadId}`, { status: res.status, streamId: id })
          return
        }
        const reader = res.body.getReader()
        const dec = new TextDecoder()
        let buffer = ''
        while (true) {
          if (wc.isDestroyed() || state.stoppedByClient || ac.signal.aborted) {
            stopStream()
            return
          }
          const { done, value } = await reader.read()
          if (done) break
          buffer += dec.decode(value, { stream: true })
          let next: { block: string; rest: string } | null
          while ((next = takeSseBlock(buffer)) !== null) {
            const block = next.block
            buffer = next.rest
            const parsed = parseSseData(block)
            if (parsed !== null) {
              if (
                !safeWebContentsSend(wc, 'runtime:sse-event', { streamId: id, data: parsed })
              ) {
                stopStream()
                return
              }
            }
          }
        }
        buffer += dec.decode()
        const trailing = buffer.trim()
        if (trailing) {
          const parsed = parseSseData(trailing)
          if (parsed !== null) {
            if (
              !safeWebContentsSend(wc, 'runtime:sse-event', { streamId: id, data: parsed })
            ) {
              stopStream()
              return
            }
          }
        }
        if (!state.stoppedByClient && !ac.signal.aborted) {
          safeWebContentsSend(wc, 'runtime:sse-end', { streamId: id })
        }
      } catch (e) {
        if (state.stoppedByClient || ac.signal.aborted) {
          return
        }
        const msg = e instanceof Error ? e.message : String(e)
        safeWebContentsSend(wc, 'runtime:sse-error', { streamId: id, message: msg })
        logError('sse', `SSE stream error for thread ${request.threadId}`, { message: msg, streamId: id })
      } finally {
        sseControllers.delete(id)
      }
    })().catch((e) => {
      if (state.stoppedByClient || ac.signal.aborted) return
      logError('sse', `SSE stream task failed for thread ${request.threadId}`, {
        message: e instanceof Error ? e.message : String(e),
        streamId: id
      })
    })

    return { streamId: id }
  })

  ipcMain.handle('runtime:sse:stop', async (_, streamId: unknown) => {
    const normalizedStreamId = streamIdSchema.parse(streamId)
    const state = sseControllers.get(normalizedStreamId)
    if (state) {
      state.stoppedByClient = true
      state.controller.abort()
    }
    return true
  })

  // Settings UI "Regenerate" button: drop the cached token file, recycle the
  // managed runtime so it picks up a fresh value, and return the fingerprint
  // (8-char prefix) for display. Returns ok:false if the runtime cannot be
  // restarted (e.g., user has no API key) — callers should leave the prior
  // token displayed and surface the error.
  ipcMain.handle('runtime:regenerate-token', async () => {
    try {
      invalidateRuntimeReady('regenerate-token')
      clearRuntimeTokenFile()
      await stopDeepseekChildAndWait()
      const settings = await store.load()
      if (!resolveConfiguredApiKey(settings)) {
        // No API key → cannot start runtime; the next spawn attempt will
        // generate a token. Tell the UI so the fingerprint shows "—".
        return { ok: true as const, fingerprint: '', restarted: false }
      }
      await startDeepseekChild(settings)
      const ok = await waitForRuntimeHealth(settings.deepseek.port, 5_000)
      const token = readRuntimeTokenFile()
      const fingerprint = token ? `${token.slice(0, 8)}…${token.slice(-4)}` : ''
      return { ok: true as const, fingerprint, restarted: ok, tokenPath: runtimeTokenFilePath() }
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e)
      logError('runtime-regenerate', 'Failed to regenerate runtime token', { message })
      return { ok: false as const, message }
    }
  })
  traceStartup('ipc registration:done')

  createWindow()
  traceStartup('createWindow:returned')

  if (resolveConfiguredApiKey(initial)) {
    void ensureRuntime(initial).catch((error) => {
      logWarn('runtime-startup', 'Initial runtime startup failed', {
        message: error instanceof Error ? error.message : String(error)
      })
    })
  }

  void pruneOnStartup().catch((err) => {
    console.warn('[deepseek-gui] prune logs:', err)
  })

  if (resolveConfiguredApiKey(initial)) {
    setTimeout(() => {
      const launcher = resolveRuntimeLauncher(initial.deepseek.binaryPath)
      console.info('[workbench] runtime launcher:', runtimeLauncherLabel(launcher))
    }, 1500)
  }

  app.on('second-instance', () => {
    if (!mainWindow) return
    if (mainWindow.isMinimized()) mainWindow.restore()
    mainWindow.show()
    mainWindow.focus()
  })

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
}).catch((error) => {
  const message = error instanceof Error ? error.message : String(error)
  console.error('[deepseek-gui] startup failed:', error)
  dialog.showErrorBox('DeepSeek GUI failed to start', message)
  app.quit()
})

app.on('window-all-closed', () => {
  abortAllSseStreams()
  stopDeepseekChild()
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

app.on('before-quit', () => {
  abortAllSseStreams()
  stopDeepseekChild()
})
