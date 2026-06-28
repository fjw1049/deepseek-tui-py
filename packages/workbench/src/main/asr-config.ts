import { readFile, writeFile } from 'node:fs/promises'
import { DEFAULT_ASR_BASE_URL, DEFAULT_ASR_MODEL, type AsrSettingsV1 } from '../shared/app-settings'
import { parseAsrSettingsFromToml } from '../shared/asr-config'
import { upsertTomlSections } from '../shared/toml-section'
import { resolveDeepseekConfigPath } from './deepseek-paths'

function emptyAsrConfig(): AsrSettingsV1 {
  return {
    apiKey: '',
    model: DEFAULT_ASR_MODEL,
    baseUrl: DEFAULT_ASR_BASE_URL
  }
}

export function parseAsrFromConfigToml(content: string): AsrSettingsV1 {
  return parseAsrSettingsFromToml(content)
}

async function readConfigContent(path: string): Promise<string | null> {
  try {
    return await readFile(path, 'utf8')
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return null
    throw error
  }
}

async function writeConfigAt(path: string, config: AsrSettingsV1): Promise<void> {
  let content = ''
  const existing = await readConfigContent(path)
  if (existing != null) {
    content = existing
  } else {
    content = '# DeepSeek config\n\n'
  }

  const apiKey = config.apiKey.trim()
  const model = config.model.trim() || DEFAULT_ASR_MODEL
  const baseUrl = config.baseUrl.trim() || DEFAULT_ASR_BASE_URL
  const next = upsertTomlSections(content, {
    asr: {
      api_key: apiKey,
      model,
      base_url: baseUrl
    }
  })

  await writeFile(path, next, 'utf8')
}

export async function readAsrConfigFile(): Promise<{
  path: string
  exists: boolean
  config: AsrSettingsV1
}> {
  const path = resolveDeepseekConfigPath()
  const content = await readConfigContent(path)
  return {
    path,
    exists: content != null,
    config: content == null ? emptyAsrConfig() : parseAsrFromConfigToml(content)
  }
}

export async function writeAsrConfigFile(config: AsrSettingsV1): Promise<{ path: string }> {
  const path = resolveDeepseekConfigPath()
  await writeConfigAt(path, config)
  return { path }
}
