import { spawn } from 'node:child_process'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { dirname } from 'node:path'
import type { AppSettingsV1 } from '../shared/app-settings'
import {
  BUILTIN_LLM_PROVIDER_IDS,
  BUILTIN_LLM_PROVIDERS,
  normalizeCustomModelContextWindow,
  resolveProviderDefaultModel
} from '../shared/app-settings'
import { readTomlBool, upsertTomlSections } from '../shared/toml-section'
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

/**
 * Read the top-level ``api_key`` from a config.toml body (before the first
 * ``[section]``). Matching the whole file would also hit keys inside tables
 * such as ``[asr]``, which must never be treated as the chat-model key.
 */
export function readTopLevelApiKeyFromToml(tomlContent: string): string {
  const topLevel = tomlContent.split(/^\s*\[/m)[0] ?? ''
  const match = topLevel.match(/^\s*api_key\s*=\s*"([^"]*)"/m)
  return match?.[1]?.trim() ?? ''
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

/** True when builtin vendor keys/models/windows changed (needs config sync + runtime restart). */
export function llmProviderConfigChanged(prev: AppSettingsV1, next: AppSettingsV1): boolean {
  return (
    prev.defaultLlmProviderId !== next.defaultLlmProviderId ||
    JSON.stringify(prev.llmProviders) !== JSON.stringify(next.llmProviders)
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
    llmProviderConfigChanged(prev, next) ||
    prev.locale !== next.locale ||
    JSON.stringify(prev.customEndpoints) !== JSON.stringify(next.customEndpoints)
  )
}

export function localeConfigChanged(prev: AppSettingsV1, next: AppSettingsV1): boolean {
  return prev.locale !== next.locale
}

async function syncUiLocaleConfig(settings: AppSettingsV1): Promise<void> {
  const configPath = resolveDeepseekConfigPath()
  let content = ''
  try {
    content = await readFile(configPath, 'utf8')
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error
  }
  const next = upsertTomlSections(content, {
    ui: { locale: settings.locale }
  })
  await mkdir(dirname(configPath), { recursive: true })
  await writeFile(configPath, next, 'utf8')
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
  for (const section of [...removedSectionNames]) {
    removedSectionNames.add(`${section}.context_windows`)
  }
  // Per-model window tables are rewritten wholesale each sync (upsert can't
  // delete keys of removed models), so drop the current ones first too.
  for (const section of currentSectionNames) {
    removedSectionNames.add(`${section}.context_windows`)
  }
  content = removeTomlSections(content, removedSectionNames)
  const sections: Record<
    string,
    Record<string, string | number | boolean | undefined>
  > = {}
  for (const endpoint of settings.customEndpoints) {
    if (!endpoint.enabled) continue
    const defaultModel = endpoint.models.find((model) => model.enabled)?.id
    sections[`providers.${endpoint.id}`] = {
      protocol: endpoint.protocol,
      base_url: endpoint.baseUrl,
      api_key: endpoint.apiKey,
      model: defaultModel
    }
    // Context window per model (tokens), consumed by the Python runtime's
    // register_provider_context_windows. Model ids need quoting — they may
    // contain characters invalid in TOML bare keys (e.g. "glm-5.2").
    const windows: Record<string, number> = {}
    for (const model of endpoint.models) {
      if (!model.enabled || !model.id) continue
      windows[`"${model.id.replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`] =
        normalizeCustomModelContextWindow(model.contextWindow)
    }
    if (Object.keys(windows).length > 0) {
      sections[`providers.${endpoint.id}.context_windows`] = windows
    }
  }
  const next = upsertTomlSections(content, sections)
  await mkdir(dirname(configPath), { recursive: true })
  await writeFile(configPath, next, 'utf8')
}

async function syncBuiltinLlmProviderConfig(
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

  const activeIds = new Set(
    BUILTIN_LLM_PROVIDER_IDS.filter((id) => settings.llmProviders[id].apiKey.trim())
  )
  const removed = new Set(
    BUILTIN_LLM_PROVIDER_IDS.filter((id) => !activeIds.has(id)).map((id) => `providers.${id}`)
  )
  // Drop stale sections when a vendor key is cleared.
  if (previous) {
    for (const id of BUILTIN_LLM_PROVIDER_IDS) {
      if (previous.llmProviders[id].apiKey.trim() && !activeIds.has(id)) {
        removed.add(`providers.${id}`)
      }
    }
  }
  for (const section of [...removed]) {
    removed.add(`${section}.context_windows`)
  }
  // Per-model window tables are rewritten wholesale each sync.
  for (const id of activeIds) {
    removed.add(`providers.${id}.context_windows`)
  }
  content = removeTomlSections(content, removed)

  const sections: Record<
    string,
    Record<string, string | number | boolean | undefined>
  > = {}
  for (const id of activeIds) {
    const def = BUILTIN_LLM_PROVIDERS[id]
    const config = settings.llmProviders[id]
    sections[`providers.${id}`] = {
      protocol: def.protocol,
      base_url: def.baseUrl,
      api_key: config.apiKey.trim(),
      model: resolveProviderDefaultModel(id, config)
    }
    const windows: Record<string, number> = {}
    for (const model of config.models) {
      if (!model.enabled || !model.id.trim()) continue
      windows[`"${model.id.replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`] =
        normalizeCustomModelContextWindow(model.contextWindow)
    }
    if (Object.keys(windows).length > 0) {
      sections[`providers.${id}.context_windows`] = windows
    }
  }
  const next = upsertTomlSections(content, sections)
  await mkdir(dirname(configPath), { recursive: true })
  await writeFile(configPath, next, 'utf8')
}

/**
 * Workbench exposes a scheduled-task UI that requires the Runtime automation
 * manager. Ensure ``[features] automations/tasks`` are on in config.toml.
 * Returns ``changed: true`` when the file was updated (caller should restart
 * a managed Runtime so the new flags take effect).
 */
export async function ensureAutomationsFeatureEnabled(): Promise<{ changed: boolean }> {
  const configPath = resolveDeepseekConfigPath()
  let content = ''
  try {
    content = await readFile(configPath, 'utf8')
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error
  }

  const automationsOn = readTomlBool(content, 'automations', { section: 'features' }) === true
  const tasksExplicitlyOff = readTomlBool(content, 'tasks', { section: 'features' }) === false
  // Python defaults tasks=true; only rewrite when automations is off or tasks
  // was explicitly disabled (automations cannot run without tasks).
  if (automationsOn && !tasksExplicitlyOff) {
    return { changed: false }
  }

  const next = upsertTomlSections(content, {
    features: {
      automations: true,
      tasks: true
    }
  })
  if (next === content) return { changed: false }

  await mkdir(dirname(configPath), { recursive: true })
  await writeFile(configPath, next, 'utf8')
  return { changed: true }
}

export async function syncDeepseekTuiConfig(
  settings: AppSettingsV1,
  previous?: AppSettingsV1
): Promise<void> {
  if (previous && !deepseekTuiConfigChanged(previous, settings)) return

  const commands: DeepseekCommand[] = []
  const current = settings.deepseek
  const prev = previous?.deepseek
  const defaultProviderId = settings.defaultLlmProviderId
  const defaultProvider = BUILTIN_LLM_PROVIDERS[defaultProviderId]
  const defaultProviderKey = settings.llmProviders[defaultProviderId].apiKey.trim()

  if (
    !previous ||
    deepseekConfigFieldsChanged(previous, settings) ||
    llmProviderConfigChanged(previous, settings)
  ) {
    commands.push({ args: ['config', 'set', 'provider', defaultProviderId] })
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

  if (
    !previous ||
    previous.defaultLlmProviderId !== defaultProviderId ||
    previous.llmProviders[defaultProviderId].apiKey !==
      settings.llmProviders[defaultProviderId].apiKey ||
    prev?.baseUrl !== current.baseUrl
  ) {
    const baseUrl = defaultProvider.baseUrl
    commands.push(
      baseUrl
        ? { args: ['config', 'set', 'base_url', baseUrl] }
        : { args: ['config', 'unset', 'base_url'] }
    )
  }

  if (
    !previous ||
    previous.defaultLlmProviderId !== defaultProviderId ||
    previous.llmProviders[defaultProviderId].apiKey !==
      settings.llmProviders[defaultProviderId].apiKey ||
    prev?.apiKey !== current.apiKey
  ) {
    // On initial startup (no previous), read config.toml's api_key first.
    // If config.toml already has a non-empty key, don't overwrite it — the
    // user may have edited config.toml directly and the GUI cache is stale.
    let skipApiKeySync = false
    if (!previous) {
      try {
        const configPath = resolveDeepseekConfigPath()
        const tomlContent = await readFile(configPath, 'utf8')
        if (readTopLevelApiKeyFromToml(tomlContent)) {
          skipApiKeySync = true
        }
      } catch { /* file missing — proceed with sync */ }
    }
    if (!skipApiKeySync) {
      if (defaultProviderKey) {
        commands.push({ args: ['config', 'set', 'api_key', defaultProviderKey] })
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
  if (!previous || previous.locale !== settings.locale) {
    await syncUiLocaleConfig(settings)
  }
  if (!previous || llmProviderConfigChanged(previous, settings)) {
    await syncBuiltinLlmProviderConfig(settings, previous)
  }
  if (!previous || JSON.stringify(previous.customEndpoints) !== JSON.stringify(settings.customEndpoints)) {
    await syncCustomEndpointConfig(settings, previous)
  }
}
