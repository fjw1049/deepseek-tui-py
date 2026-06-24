import { spawn } from 'node:child_process'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { dirname } from 'node:path'
import type { AppSettingsV1 } from '../shared/app-settings'
import { upsertTomlSections } from '../shared/toml-section'
import {
  resolveDeepseekConfigPath,
  resolveDeepseekPaths,
  resolveMcpConfigPath,
  resolveUserDeepseekDir,
  type DeepseekPaths
} from './deepseek-paths'
import {
  resolveRepoRoot,
  resolveRuntimeLauncher,
  runtimeSpawnCwd,
  runtimeSpawnEnv,
  type RuntimeLauncher
} from './resolve-python-runtime'

export {
  resolveDeepseekConfigPath,
  resolveDeepseekPaths,
  resolveMcpConfigPath,
  resolveUserDeepseekDir,
  type DeepseekPaths
}

type DeepseekCommand = {
  args: string[]
  stdin?: string
}

const DEEPSEEK_CONFIG_COMMAND_TIMEOUT_MS = 15_000

function globalConfigArgs(): string[] {
  return ['--config', resolveDeepseekConfigPath()]
}

function deepseekConfigFieldsChanged(prev: AppSettingsV1, next: AppSettingsV1): boolean {
  const a = prev.deepseek
  const b = next.deepseek
  return (
    a.apiKey !== b.apiKey ||
    a.baseUrl !== b.baseUrl ||
    a.approvalPolicy !== b.approvalPolicy ||
    a.sandboxMode !== b.sandboxMode
  )
}

async function runDeepseekCommand(
  launcher: RuntimeLauncher,
  command: DeepseekCommand
): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    const proc = spawn(launcher.bin, [...launcher.prefixArgs, ...globalConfigArgs(), ...command.args], {
      env: runtimeSpawnEnv(),
      cwd: runtimeSpawnCwd(),
      stdio: ['pipe', 'pipe', 'pipe'],
      windowsHide: true
    })

    let stdout = ''
    let stderr = ''
    let settled = false

    const finish = (fn: () => void): void => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      fn()
    }

    const timer = setTimeout(() => {
      finish(() => {
        proc.kill()
        reject(
          new Error(
            `deepseek-tui ${command.args.join(' ')} timed out after ${DEEPSEEK_CONFIG_COMMAND_TIMEOUT_MS}ms`
          )
        )
      })
    }, DEEPSEEK_CONFIG_COMMAND_TIMEOUT_MS)

    proc.stdout.on('data', (chunk) => {
      stdout += String(chunk)
    })
    proc.stderr.on('data', (chunk) => {
      stderr += String(chunk)
    })
    proc.once('error', (error) => finish(() => reject(error)))
    proc.once('exit', (code, signal) => {
      finish(() => {
        if (code === 0) {
          resolve()
          return
        }
        const detail = stderr.trim() || stdout.trim() || `signal ${signal ?? 'null'}`
        reject(new Error(`deepseek-tui ${command.args.join(' ')} failed: ${detail}`))
      })
    })

    proc.stdin.end(command.stdin ?? '')
  })
}

export function deepseekTuiConfigChanged(prev: AppSettingsV1, next: AppSettingsV1): boolean {
  return (
    deepseekConfigFieldsChanged(prev, next) ||
    JSON.stringify(prev.customEndpoints) !== JSON.stringify(next.customEndpoints)
  )
}

function removeTomlSections(content: string, sectionNames: Set<string>): string {
  if (sectionNames.size === 0) return content
  const lines = content.split(/\r?\n/)
  const output: string[] = []
  let skipping = false
  for (const line of lines) {
    const section = line.match(/^\s*\[([^\]]+)\]\s*$/)
    if (section) skipping = sectionNames.has(section[1].trim())
    if (!skipping) output.push(line)
  }
  return output.join('\n')
}

async function syncCustomEndpointConfig(
  settings: AppSettingsV1,
  previous?: AppSettingsV1
): Promise<void> {
  const configPath = resolveDeepseekConfigPath()
  let content = ''
  try {
    content = await readFile(configPath, 'utf8')
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error
  }
  const currentSectionNames = new Set(
    settings.customEndpoints.filter((endpoint) => endpoint.enabled).map(
      (endpoint) => `providers.${endpoint.id}`
    )
  )
  const removedSectionNames = new Set(
    [
      ...(previous?.customEndpoints ?? []),
      ...settings.customEndpoints.filter((endpoint) => !endpoint.enabled)
    ]
      .map((endpoint) => `providers.${endpoint.id}`)
      .filter((section) => !currentSectionNames.has(section))
  )
  content = removeTomlSections(content, removedSectionNames)
  const sections: Record<string, Record<string, string | boolean | undefined>> = {}
  for (const endpoint of settings.customEndpoints) {
    if (!endpoint.enabled) continue
    const defaultModel = endpoint.models.find((model) => model.enabled)?.id
    sections[`providers.${endpoint.id}`] = {
      protocol: endpoint.protocol,
      base_url: endpoint.baseUrl,
      api_key: endpoint.apiKey,
      model: defaultModel
    }
  }
  const next = upsertTomlSections(content, sections)
  await mkdir(dirname(configPath), { recursive: true })
  await writeFile(configPath, next, 'utf8')
}

export async function syncDeepseekTuiConfig(
  settings: AppSettingsV1,
  previous?: AppSettingsV1
): Promise<void> {
  if (previous && !deepseekTuiConfigChanged(previous, settings)) return

  const commands: DeepseekCommand[] = []
  const current = settings.deepseek
  const prev = previous?.deepseek

  if (!previous || deepseekConfigFieldsChanged(previous, settings)) {
    commands.push({ args: ['config', 'set', 'provider', 'deepseek'] })
  }

  if (!prev || prev.approvalPolicy !== current.approvalPolicy) {
    commands.push({
      args: ['config', 'set', 'approval_policy', current.approvalPolicy]
    })
  }

  if (!prev || prev.sandboxMode !== current.sandboxMode) {
    commands.push({
      args: ['config', 'set', 'sandbox_mode', current.sandboxMode]
    })
  }

  if (!prev || prev.baseUrl !== current.baseUrl) {
    const baseUrl = current.baseUrl.trim()
    commands.push(
      baseUrl
        ? { args: ['config', 'set', 'base_url', baseUrl] }
        : { args: ['config', 'unset', 'base_url'] }
    )
  }

  if (!prev || prev.apiKey !== current.apiKey) {
    // On initial startup (no previous), read config.toml's api_key first.
    // If config.toml already has a non-empty key, don't overwrite it — the
    // user may have edited config.toml directly and the GUI cache is stale.
    let skipApiKeySync = false
    if (!prev) {
      try {
        const configPath = resolveDeepseekConfigPath()
        const tomlContent = await readFile(configPath, 'utf8')
        const match = tomlContent.match(/^\s*api_key\s*=\s*"([^"]*)"/m)
        if (match && match[1].trim()) {
          skipApiKeySync = true
        }
      } catch { /* file missing — proceed with sync */ }
    }
    if (!skipApiKeySync) {
      const apiKey = current.apiKey.trim()
      if (apiKey) {
        commands.push({ args: ['config', 'set', 'api_key', apiKey] })
      } else {
        commands.push({ args: ['config', 'unset', 'api_key'] })
      }
    }
  }

  if (commands.length > 0) {
    const launcher = resolveRuntimeLauncher(settings.deepseek.binaryPath)
    for (const command of commands) {
      await runDeepseekCommand(launcher, command)
    }
  }
  if (!previous || JSON.stringify(previous.customEndpoints) !== JSON.stringify(settings.customEndpoints)) {
    await syncCustomEndpointConfig(settings, previous)
  }
}
