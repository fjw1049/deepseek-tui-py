import {
  BUILTIN_LLM_PROVIDERS,
  DEFAULT_DEEPSEEK_BASE_URL,
  isBuiltinLlmProviderId,
  type AppSettingsV1,
  type BuiltinLlmProviderId
} from '../shared/app-settings'
import { DEFAULT_COMPOSER_MODEL_IDS } from '../shared/default-composer-models'
import { upstreamOpenAiModelsUrl } from '../shared/openai-compat-url'

export type FetchUpstreamModelsResult =
  | { ok: true; modelIds: string[]; source: 'upstream' | 'fallback' }
  | { ok: false; message: string; fallbackModelIds: string[] }

const UPSTREAM_MODELS_TIMEOUT_MS = 8_000

export function fallbackModelIds(): string[] {
  return [...DEFAULT_COMPOSER_MODEL_IDS]
}

export async function fetchOpenAiCompatibleModelIds(
  baseUrl: string,
  apiKey: string
): Promise<FetchUpstreamModelsResult> {
  const key = apiKey.trim()
  const fallbackModelIds = fallbackModelIdsForBase(baseUrl)
  if (!key) {
    return {
      ok: false,
      message: 'Missing API key; cannot query upstream /v1/models.',
      fallbackModelIds
    }
  }
  const url = upstreamOpenAiModelsUrl(baseUrl || DEFAULT_DEEPSEEK_BASE_URL)
  try {
    const res = await fetch(url, {
      method: 'GET',
      headers: {
        Accept: 'application/json',
        Authorization: `Bearer ${key}`
      },
      signal: AbortSignal.timeout(UPSTREAM_MODELS_TIMEOUT_MS)
    })
    const text = await res.text()
    if (!res.ok) {
      return {
        ok: false,
        message: `Upstream models request failed (${res.status}): ${text.slice(0, 400)}`,
        fallbackModelIds
      }
    }
    let parsed: unknown
    try {
      parsed = JSON.parse(text) as unknown
    } catch {
      return {
        ok: false,
        message: 'Upstream /v1/models returned non-JSON body.',
        fallbackModelIds
      }
    }
    const data = (parsed as { data?: unknown }).data
    if (!Array.isArray(data)) {
      return {
        ok: false,
        message: 'Upstream /v1/models JSON missing data[] array.',
        fallbackModelIds
      }
    }
    const ids = new Set<string>()
    for (const row of data) {
      if (row && typeof row === 'object' && typeof (row as { id?: unknown }).id === 'string') {
        const id = (row as { id: string }).id.trim()
        if (id) ids.add(id)
      }
    }
    const sorted = [...ids].sort((a, b) => a.localeCompare(b))
    if (sorted.length === 0) {
      return {
        ok: false,
        message: 'Upstream returned an empty model list.',
        fallbackModelIds
      }
    }
    return { ok: true, modelIds: sorted, source: 'upstream' }
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e)
    return { ok: false, message: msg, fallbackModelIds }
  }
}

function fallbackModelIdsForBase(baseUrl: string): string[] {
  const normalized = baseUrl.trim().replace(/\/+$/, '')
  for (const def of Object.values(BUILTIN_LLM_PROVIDERS)) {
    if (def.baseUrl.replace(/\/+$/, '') === normalized) {
      return [...def.fallbackModels]
    }
  }
  return fallbackModelIds()
}

/** Legacy: fetch models for the default DeepSeek / default LLM provider. */
export async function fetchUpstreamModelIds(
  settings: AppSettingsV1,
  apiKey: string
): Promise<FetchUpstreamModelsResult> {
  const providerId = settings.defaultLlmProviderId
  const def = BUILTIN_LLM_PROVIDERS[providerId]
  const key = apiKey.trim() || settings.llmProviders[providerId]?.apiKey?.trim() || ''
  return fetchOpenAiCompatibleModelIds(def.baseUrl, key)
}

export async function fetchBuiltinProviderModelIds(
  settings: AppSettingsV1,
  providerId: string
): Promise<FetchUpstreamModelsResult> {
  if (!isBuiltinLlmProviderId(providerId)) {
    return {
      ok: false,
      message: `Unknown built-in provider: ${providerId}`,
      fallbackModelIds: fallbackModelIds()
    }
  }
  const id = providerId as BuiltinLlmProviderId
  const def = BUILTIN_LLM_PROVIDERS[id]
  const key = settings.llmProviders[id]?.apiKey?.trim() ?? ''
  const result = await fetchOpenAiCompatibleModelIds(def.baseUrl, key)
  if (!result.ok) {
    return {
      ...result,
      fallbackModelIds: [...def.fallbackModels]
    }
  }
  return result
}
