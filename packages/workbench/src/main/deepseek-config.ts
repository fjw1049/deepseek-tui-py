import { spawn } from 'node:child_process'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { dirname } from 'node:path'
import { defaultMemorySettings } from '../shared/app-settings'
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

function memoryConfigFieldsChanged(prev: AppSettingsV1, next: AppSettingsV1): boolean {
  return JSON.stringify(prev.memory) !== JSON.stringify(next.memory)
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
  return deepseekConfigFieldsChanged(prev, next) || memoryConfigFieldsChanged(prev, next)
}

async function syncMemoryConfig(settings: AppSettingsV1): Promise<void> {
  const configPath = resolveDeepseekConfigPath()
  let content = ''
  try {
    content = await readFile(configPath, 'utf8')
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error
  }
  const memory = settings.memory ?? defaultMemorySettings()
  const smart = memory.smart
  const next = upsertTomlSections(content, {
    memory: {
      enabled: memory.enabled,
      mode: memory.mode
    },
    'memory.smart': {
      enabled: smart.enabled,
      data_dir: smart.dataDir || undefined,
      recall_enabled: smart.recallEnabled,
      capture_enabled: smart.captureEnabled,
      recall_timeout_ms: smart.recallTimeoutMs,
      recall_score_threshold: smart.recallScoreThreshold,
      recall_limit: smart.recallLimit,
      capture_min_user_chars: smart.captureMinUserChars,
      l1_every_n: smart.l1EveryN,
      l1_idle_timeout_seconds: smart.l1IdleTimeoutSeconds,
      l1_confidence_min: smart.l1ConfidenceMin,
      l1_max_per_session: smart.l1MaxPerSession,
      l1_decay_half_life_days: smart.l1DecayHalfLifeDays,
      hybrid_search: smart.hybridSearch,
      fts_tokenizer: smart.ftsTokenizer,
      embedding_provider: smart.embeddingProvider,
      embedding_model: smart.embeddingModel,
      embedding_base_url: smart.embeddingBaseUrl || undefined,
      embedding_api_key: smart.embeddingApiKey || undefined,
      embedding_dimensions: smart.embeddingDimensions ?? undefined,
      embedding_dedup_threshold: smart.embeddingDedupThreshold,
      embedding_backfill_on_start: smart.embeddingBackfillOnStart
    }
  })
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
    const apiKey = current.apiKey.trim()
    if (apiKey) {
      commands.push({ args: ['config', 'set', 'api_key', apiKey] })
    } else {
      commands.push({ args: ['config', 'unset', 'api_key'] })
    }
  }

  if (commands.length > 0) {
    const launcher = resolveRuntimeLauncher(settings.deepseek.binaryPath)
    for (const command of commands) {
      await runDeepseekCommand(launcher, command)
    }
  }
  if (!previous || memoryConfigFieldsChanged(previous, settings)) {
    await syncMemoryConfig(settings)
  }
}
