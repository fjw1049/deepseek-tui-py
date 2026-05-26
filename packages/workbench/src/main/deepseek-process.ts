import { execFile, spawn, type ChildProcess } from 'node:child_process'
import { existsSync, mkdirSync, readFileSync, writeFileSync, chmodSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { randomBytes } from 'node:crypto'
import type { AppSettingsV1 } from '../shared/app-settings'
import {
  resolveRuntimeLauncher,
  runtimeLauncherLabel,
  runtimeSpawnCwd,
  runtimeSpawnEnv
} from './resolve-python-runtime'
import { resolveDeepseekConfigPath } from './deepseek-config'
import { getRuntimeBaseUrl } from './settings-store'

let child: ChildProcess | null = null
let lastResolvedBinary: string | null = null

function runtimeTokenFilePath(): string {
  const base = process.env.DEEPSEEK_HOME?.trim() || join(homedir(), '.deepseek')
  return join(base, 'runtime.token')
}

function resolveOrCreateRuntimeToken(): string {
  const path = runtimeTokenFilePath()
  if (existsSync(path)) {
    try {
      const cached = readFileSync(path, 'utf8').trim()
      if (cached) return cached
    } catch {
      /* fall through */
    }
  }
  const token = `dst_${randomBytes(16).toString('hex')}${randomBytes(16).toString('hex')}`
  try {
    mkdirSync(join(path, '..'), { recursive: true })
    writeFileSync(path, token, { encoding: 'utf8' })
    try {
      chmodSync(path, 0o600)
    } catch {
      /* best-effort on platforms without POSIX perms */
    }
  } catch (err) {
    process.stderr.write(`[deepseek] runtime token cache write failed: ${String(err)}\n`)
  }
  return token
}

type PortOwner = {
  pid: number
  command: string
  parentPid: number | null
  parentCommand: string | null
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function execFileText(file: string, args: string[]): Promise<string> {
  return new Promise((resolve, reject) => {
    execFile(file, args, { encoding: 'utf8' }, (error, stdout) => {
      if (error) {
        reject(error)
        return
      }
      resolve(stdout)
    })
  })
}

function isDeepseekCommand(command: string): boolean {
  const lowered = command.toLowerCase()
  return (
    lowered.includes('deepseek') ||
    lowered.includes('deepseek_tui') ||
    lowered.includes('deepseek-tui') ||
    (lowered.includes('python') && lowered.includes('deepseek_tui'))
  )
}

export async function findListeningProcessOnPort(port: number): Promise<PortOwner | null> {
  if (process.platform === 'win32') return null

  try {
    const pidText = await execFileText('lsof', ['-nP', `-iTCP:${port}`, '-sTCP:LISTEN', '-t'])
    const pid = Number(pidText.trim().split('\n')[0] ?? '')
    if (!Number.isInteger(pid) || pid <= 0) return null
    const command = (await execFileText('ps', ['-p', String(pid), '-o', 'command='])).trim()
    const ppidText = (await execFileText('ps', ['-p', String(pid), '-o', 'ppid='])).trim()
    const parentPid = Number(ppidText)
    let parentCommand: string | null = null
    if (Number.isInteger(parentPid) && parentPid > 1) {
      try {
        parentCommand = (await execFileText('ps', ['-p', String(parentPid), '-o', 'command='])).trim() || null
      } catch {
        parentCommand = null
      }
    }
    return {
      pid,
      command,
      parentPid: Number.isInteger(parentPid) && parentPid > 0 ? parentPid : null,
      parentCommand
    }
  } catch {
    return null
  }
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function commandHasOption(command: string, option: string, expectedValue: string): boolean {
  const opt = escapeRegExp(option)
  const value = escapeRegExp(expectedValue)
  return new RegExp(`(?:^|\\s)${opt}=${value}(?:\\s|$)`).test(command) ||
    new RegExp(`(?:^|\\s)${opt}\\s+${value}(?:\\s|$)`).test(command)
}

async function waitForPortToClose(port: number, timeoutMs = 6_000): Promise<boolean> {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const owner = await findListeningProcessOnPort(port)
    if (!owner) return true
    await sleep(150)
  }
  return false
}

export function getLastResolvedDeepseekBinary(): string | null {
  return lastResolvedBinary
}

export function isDeepseekChildRunning(): boolean {
  return child !== null && !child.killed
}

export function stopDeepseekChild(): void {
  if (child && !child.killed) {
    child.kill('SIGTERM')
  }
  child = null
}

export async function stopDeepseekChildAndWait(timeoutMs = 5_000): Promise<void> {
  const proc = child
  if (!proc) return
  if (proc.killed) {
    if (child === proc) child = null
    return
  }

  await new Promise<void>((resolve) => {
    let done = false
    const finish = (): void => {
      if (done) return
      done = true
      clearTimeout(timer)
      proc.off('exit', finish)
      proc.off('error', finish)
      if (child === proc) child = null
      resolve()
    }
    const timer = setTimeout(finish, timeoutMs)
    proc.once('exit', finish)
    proc.once('error', finish)
    proc.kill('SIGTERM')
  })
}

export async function inspectDeepseekLaunchConfig(
  settings: AppSettingsV1
): Promise<
  | { state: 'absent' }
  | { state: 'non-deepseek'; pid: number; command: string }
  | { state: 'deepseek'; pid: number; command: string; matches: true }
  | { state: 'deepseek'; pid: number; command: string; matches: false; reason: string }
> {
  const owner = await findListeningProcessOnPort(settings.deepseek.port)
  if (!owner) return { state: 'absent' }

  const command = [owner.parentCommand, owner.command].filter(Boolean).join('\n')
  if (!isDeepseekCommand(command)) {
    return { state: 'non-deepseek', pid: owner.pid, command: owner.command }
  }

  const mismatches: string[] = []
  const policy = settings.deepseek.approvalPolicy
  if (policy && !commandHasOption(command, '--approval-policy', policy)) {
    mismatches.push(`approval policy is not ${policy}`)
  }
  const sandbox = settings.deepseek.sandboxMode
  if (sandbox && !commandHasOption(command, '--sandbox-mode', sandbox)) {
    mismatches.push(`sandbox mode is not ${sandbox}`)
  }
  const baseUrl = settings.deepseek.baseUrl?.trim() ?? ''
  if (baseUrl && !commandHasOption(command, '--base-url', baseUrl)) {
    mismatches.push(`base url is not ${baseUrl}`)
  }

  if (mismatches.length === 0) {
    return { state: 'deepseek', pid: owner.pid, command, matches: true }
  }
  return {
    state: 'deepseek',
    pid: owner.pid,
    command,
    matches: false,
    reason: mismatches.join('; ')
  }
}

/**
 * Best-effort recovery for an incompatible local runtime already bound to the
 * configured port. Only terminates processes whose command line clearly looks
 * like a DeepSeek runtime, so we do not kill unrelated listeners.
 */
export async function reclaimDeepseekPort(
  port: number
): Promise<{ ok: true } | { ok: false; message: string }> {
  if (child && !child.killed) {
    await stopDeepseekChildAndWait()
    if (await waitForPortToClose(port)) {
      return { ok: true }
    }
  }

  const owner = await findListeningProcessOnPort(port)
  if (!owner) return { ok: true }

  if (!isDeepseekCommand(owner.command)) {
    return {
      ok: false,
      message: `Port ${port} is already in use by another process. Stop that process or change the runtime port in Settings.`
    }
  }

  try {
    process.kill(owner.pid, 'SIGTERM')
  } catch {
    return {
      ok: false,
      message: `A DeepSeek runtime is already listening on port ${port}, and the GUI could not stop it automatically. Restart the app or free that port in Settings.`
    }
  }

  if (await waitForPortToClose(port)) {
    return { ok: true }
  }

  try {
    process.kill(owner.pid, 'SIGKILL')
  } catch {
    return {
      ok: false,
      message: `A DeepSeek runtime is still holding port ${port}. Restart the app or free that port in Settings.`
    }
  }

  if (await waitForPortToClose(port, 3_000)) {
    return { ok: true }
  }

  return {
    ok: false,
    message: `A DeepSeek runtime is still holding port ${port}. Restart the app or free that port in Settings.`
  }
}

/**
 * Spawn Python `deepseek-tui serve --http` (Workbench) or a custom binary when configured.
 */
export async function startDeepseekChild(settings: AppSettingsV1): Promise<void> {
  if (isDeepseekChildRunning()) return
  const launcher = resolveRuntimeLauncher(settings.deepseek.binaryPath)
  lastResolvedBinary = runtimeLauncherLabel(launcher)
  const port = settings.deepseek.port

  const args: string[] = [...launcher.prefixArgs]
  const policy = settings.deepseek.approvalPolicy
  if (policy) args.push('--approval-policy', policy)
  const sandbox = settings.deepseek.sandboxMode
  if (sandbox) args.push('--sandbox-mode', sandbox)
  const baseUrl = settings.deepseek.baseUrl?.trim() ?? ''
  if (baseUrl) args.push('--base-url', baseUrl)

  args.push('serve', '--http', '--host', '127.0.0.1', '--port', String(port))
  args.push('--config', resolveDeepseekConfigPath())

  // Token resolution order (mirrors Python ``resolve_runtime_auth``):
  //   1. settings.deepseek.runtimeToken (explicit user-set in GUI)
  //   2. ~/.deepseek/runtime.token (cached generated token, shared with Python)
  //   3. fresh local-only token written to (2)
  // Only fall back to ``--insecure`` if the user explicitly cleared the token
  // path via env (``DEEPSEEK_INSECURE_RUNTIME=1``); otherwise we always pass
  // a bearer so the runtime never exposes /v1 unauthenticated.
  const explicitInsecure = process.env.DEEPSEEK_INSECURE_RUNTIME === '1'
  const runtimeToken = settings.deepseek.runtimeToken?.trim() ?? ''
  if (explicitInsecure && !runtimeToken) {
    args.push('--insecure')
  } else {
    const token = runtimeToken || resolveOrCreateRuntimeToken()
    args.push('--auth-token', token)
  }

  for (const origin of settings.deepseek.extraCorsOrigins) {
    const o = origin.trim()
    if (o) args.push('--cors-origin', o)
  }

  const env = runtimeSpawnEnv()
  if (settings.deepseek.apiKey) env.DEEPSEEK_API_KEY = settings.deepseek.apiKey

  const proc = spawn(launcher.bin, args, {
    env,
    cwd: runtimeSpawnCwd(),
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true
  })
  child = proc
  let stdout = ''
  let stderr = ''
  const appendOutput = (current: string, chunk: unknown): string =>
    `${current}${String(chunk)}`.slice(-8_000)
  proc.stdout?.on('data', (d) => {
    stdout = appendOutput(stdout, d)
    process.stdout.write(`[deepseek] ${d}`)
  })
  proc.stderr?.on('data', (d) => {
    stderr = appendOutput(stderr, d)
    process.stderr.write(`[deepseek] ${d}`)
  })
  proc.on('exit', () => {
    if (child === proc) child = null
  })
  await new Promise<void>((resolve, reject) => {
    const cleanup = (): void => {
      proc.off('spawn', onSpawn)
      proc.off('error', onError)
      proc.off('exit', onEarlyExit)
    }
    const onSpawn = (): void => {
      cleanup()
      resolve()
    }
    const onError = (error: Error): void => {
      cleanup()
      if (child === proc) child = null
      reject(error)
    }
    const onEarlyExit = (code: number | null, signal: NodeJS.Signals | null): void => {
      cleanup()
      if (child === proc) child = null
      const detail = [stderr.trim(), stdout.trim()].filter(Boolean).join('\n')
      reject(
        new Error(
          `deepseek exited before startup (code ${code ?? 'null'}, signal ${signal ?? 'null'})${
            detail ? `:\n${detail}` : ''
          }`
        )
      )
    }
    proc.once('spawn', onSpawn)
    proc.once('error', onError)
    proc.once('exit', onEarlyExit)
  })
}

export async function waitForRuntimeHealth(port: number, timeoutMs = 15_000): Promise<boolean> {
  const base = getRuntimeBaseUrl(port)
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`${base}/health`, { signal: AbortSignal.timeout(1500) })
      if (res.ok) return true
    } catch {
      /* retry */
    }
    await new Promise((r) => setTimeout(r, 400))
  }
  return false
}
