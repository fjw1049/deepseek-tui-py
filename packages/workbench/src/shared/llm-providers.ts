/** Built-in LLM vendor catalogue for Settings → Models. */

import {
  CUSTOM_MODEL_CONTEXT_WINDOW_DEFAULT,
  normalizeCustomModelContextWindow
} from './app-settings-context-window'

export const BUILTIN_LLM_PROVIDER_IDS = [
  'deepseek',
  'kimi',
  'glm',
  'volcengine-ark'
] as const

export type BuiltinLlmProviderId = (typeof BUILTIN_LLM_PROVIDER_IDS)[number]

export type BuiltinLlmProviderDef = {
  id: BuiltinLlmProviderId
  /** Fixed OpenAI-compatible base URL (not user-editable). */
  baseUrl: string
  protocol: 'openai'
  /** Shown when /models fetch fails. */
  fallbackModels: string[]
  /** Default model written to config.toml when none selected. */
  defaultModel: string
}

export const BUILTIN_LLM_PROVIDERS: Record<BuiltinLlmProviderId, BuiltinLlmProviderDef> = {
  deepseek: {
    id: 'deepseek',
    baseUrl: 'https://api.deepseek.com',
    protocol: 'openai',
    fallbackModels: ['deepseek-v4-pro', 'deepseek-v4-flash'],
    defaultModel: 'deepseek-v4-pro'
  },
  kimi: {
    id: 'kimi',
    baseUrl: 'https://api.kimi.com/coding/v1',
    protocol: 'openai',
    fallbackModels: ['kimi-k3', 'kimi-k2.7-code', 'kimi-k2.6'],
    defaultModel: 'kimi-k3'
  },
  glm: {
    id: 'glm',
    baseUrl: 'https://open.bigmodel.cn/api/paas/v4',
    protocol: 'openai',
    fallbackModels: ['glm-5.1', 'glm-4.7', 'glm-4.7-flash'],
    defaultModel: 'glm-5.1'
  },
  'volcengine-ark': {
    id: 'volcengine-ark',
    baseUrl: 'https://ark.cn-beijing.volces.com/api/coding/v3',
    protocol: 'openai',
    fallbackModels: ['glm-5.1', 'kimi-k2.6', 'deepseek-v4-flash', 'doubao-seed-2.0-code'],
    defaultModel: 'glm-5.1'
  }
}

export const DEFAULT_LLM_PROVIDER_ID: BuiltinLlmProviderId = 'deepseek'

export type LlmProviderModelV1 = {
  id: string
  enabled: boolean
  contextWindow: number
}

export type LlmProviderConfigV1 = {
  apiKey: string
  /** Models shown/enabled under this vendor (name + context window). */
  models: LlmProviderModelV1[]
  /** Last successful /models listing (informational + UI seed). */
  lastFetchedModels?: string[]
  /** Model ids explicitly removed in Settings; excluded from automatic refresh results. */
  hiddenModels?: string[]
}

export function isBuiltinLlmProviderId(value: unknown): value is BuiltinLlmProviderId {
  return (
    typeof value === 'string' &&
    (BUILTIN_LLM_PROVIDER_IDS as readonly string[]).includes(value)
  )
}

export function defaultLlmProviderConfig(): LlmProviderConfigV1 {
  return { apiKey: '', models: [] }
}

export function defaultLlmProviders(): Record<BuiltinLlmProviderId, LlmProviderConfigV1> {
  return {
    deepseek: defaultLlmProviderConfig(),
    kimi: defaultLlmProviderConfig(),
    glm: defaultLlmProviderConfig(),
    'volcengine-ark': defaultLlmProviderConfig()
  }
}

export function providerHasApiKey(
  providers: Record<BuiltinLlmProviderId, LlmProviderConfigV1>,
  id: BuiltinLlmProviderId
): boolean {
  return Boolean(providers[id]?.apiKey?.trim())
}

export function enabledLlmModelIds(config: LlmProviderConfigV1): string[] {
  return config.models.filter((m) => m.enabled && m.id.trim()).map((m) => m.id.trim())
}

export function resolveProviderDefaultModel(
  id: BuiltinLlmProviderId,
  config: LlmProviderConfigV1
): string {
  const enabled = enabledLlmModelIds(config)
  if (enabled[0]) return enabled[0]
  const fetched = (config.lastFetchedModels ?? []).map((m) => m.trim()).filter(Boolean)
  if (fetched[0]) return fetched[0]
  return BUILTIN_LLM_PROVIDERS[id].defaultModel
}

export function normalizeLlmProviderModels(raw: unknown): LlmProviderModelV1[] {
  if (!Array.isArray(raw)) return []
  const seen = new Set<string>()
  const out: LlmProviderModelV1[] = []
  for (const row of raw) {
    if (!row || typeof row !== 'object') continue
    const source = row as Partial<LlmProviderModelV1> & { id?: unknown }
    const id = typeof source.id === 'string' ? source.id.trim() : ''
    if (!id || seen.has(id)) continue
    seen.add(id)
    out.push({
      id,
      enabled: source.enabled !== false,
      contextWindow: normalizeCustomModelContextWindow(
        source.contextWindow ?? CUSTOM_MODEL_CONTEXT_WINDOW_DEFAULT
      )
    })
  }
  return out
}

/** Migrate legacy `enabledModels: string[]` into `models[]`. */
export function migrateEnabledModelsToModels(
  enabledModels: unknown,
  existingModels: LlmProviderModelV1[]
): LlmProviderModelV1[] {
  if (existingModels.length > 0) return existingModels
  if (!Array.isArray(enabledModels)) return []
  const seen = new Set<string>()
  const out: LlmProviderModelV1[] = []
  for (const row of enabledModels) {
    const id = typeof row === 'string' ? row.trim() : ''
    if (!id || seen.has(id)) continue
    seen.add(id)
    out.push({
      id,
      enabled: true,
      contextWindow: CUSTOM_MODEL_CONTEXT_WINDOW_DEFAULT
    })
  }
  return out
}
