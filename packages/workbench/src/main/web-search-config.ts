import { readFile, writeFile } from 'node:fs/promises'
import {
  defaultWebSearchSettings,
  enabledWebSearchProviderIds,
  normalizeWebSearchSettings,
  type WebSearchSettingsV1
} from '../shared/app-settings'
import {
  readTomlTopLevelString,
  readTomlTopLevelStringArray,
  upsertTomlTopLevel
} from '../shared/toml-section'
import { resolveDeepseekConfigPath } from './deepseek-paths'

async function readConfigContent(path: string): Promise<string | null> {
  try {
    return await readFile(path, 'utf8')
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return null
    throw error
  }
}

export function parseWebSearchFromConfigToml(content: string): {
  settings: WebSearchSettingsV1
  hasAnyKey: boolean
} {
  const anysearchApiKey = readTomlTopLevelString(content, 'anysearch_api_key') ?? ''
  const tavilyApiKey = readTomlTopLevelString(content, 'tavily_api_key') ?? ''
  const providers = readTomlTopLevelStringArray(content, 'web_search_providers')
  const settings = normalizeWebSearchSettings(undefined, {
    anysearchApiKey,
    tavilyApiKey,
    providers
  })
  return {
    settings,
    hasAnyKey: Boolean(anysearchApiKey || tavilyApiKey || providers)
  }
}

async function writeConfigAt(path: string, settings: WebSearchSettingsV1): Promise<void> {
  let content = ''
  const existing = await readConfigContent(path)
  if (existing != null) {
    content = existing
  } else {
    content = '# DeepSeek config\n\n'
  }

  const enabled = enabledWebSearchProviderIds(settings)
  const next = upsertTomlTopLevel(content, {
    anysearch_api_key: settings.providers.anysearch.apiKey.trim(),
    tavily_api_key: settings.providers.tavily.apiKey.trim(),
    web_search_providers: enabled
  })
  await writeFile(path, next, 'utf8')
}

export async function readWebSearchConfigFile(): Promise<{
  path: string
  exists: boolean
  settings: WebSearchSettingsV1
  hasAnyKey: boolean
}> {
  const path = resolveDeepseekConfigPath()
  const content = await readConfigContent(path)
  if (content == null) {
    return {
      path,
      exists: false,
      settings: defaultWebSearchSettings(),
      hasAnyKey: false
    }
  }
  const parsed = parseWebSearchFromConfigToml(content)
  return {
    path,
    exists: true,
    settings: parsed.settings,
    hasAnyKey: parsed.hasAnyKey
  }
}

export async function writeWebSearchConfigFile(
  settings: WebSearchSettingsV1
): Promise<{ path: string }> {
  const path = resolveDeepseekConfigPath()
  await writeConfigAt(path, normalizeWebSearchSettings(settings))
  return { path }
}
