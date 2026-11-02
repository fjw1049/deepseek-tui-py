import type { AppSettingsV1 } from '../../shared/app-settings'
import {
  BUILTIN_LLM_PROVIDERS,
  enabledLlmModelIds,
  resolveProviderDefaultModel
} from '../../shared/llm-providers'
import type { PetReactionRequest, PetReactionResult } from '../../shared/pet-manifest'
import { buildEndpointProbeUrl } from '../ipc/endpoint-compat-probe'

const TIMEOUT_MS = 8000
// Thinking models spend part of the budget before the visible line.
const MAX_TOKENS = 300
const MAX_LINE_CHARS = 60

const REASON_HINTS: Record<PetReactionRequest['reason'], string> = {
  turn_done: 'The assistant just finished a long task.',
  turn_recovered: 'The assistant finished, after recovering from some tool errors on the way.',
  tests_failed: 'The last test run in this task failed.',
  large_diff: 'The assistant just changed a lot of code at once.',
  petted: 'The user just patted you.',
  named: 'The user mentioned you by name in their message.'
}

/** A cheap model is enough for one line; prefer a "flash"/"lite" one when the vendor has it. */
export function pickPetReactionModel(settings: AppSettingsV1): { model: string; apiKey: string; baseUrl: string } | null {
  const id = settings.defaultLlmProviderId
  const config = settings.llmProviders[id]
  const apiKey = config?.apiKey.trim() ||
    (id === 'deepseek' ? settings.deepseek.apiKey.trim() || process.env.DEEPSEEK_API_KEY?.trim() || '' : '')
  if (!config || !apiKey) return null
  const candidates = [
    ...enabledLlmModelIds(config),
    ...(config.lastFetchedModels ?? []),
    ...BUILTIN_LLM_PROVIDERS[id].fallbackModels
  ]
  const light = candidates.find((model) => /flash|lite|mini|air/i.test(model))
  return {
    model: light ?? resolveProviderDefaultModel(id, config),
    apiKey,
    baseUrl: BUILTIN_LLM_PROVIDERS[id].baseUrl
  }
}

export function buildPetReactionMessages(request: PetReactionRequest): Array<{ role: string; content: string }> {
  const language = request.locale.toLowerCase().startsWith('zh') ? 'Simplified Chinese' : 'English'
  const system = [
    `You are ${request.petName}, a small pet that sits above a coding assistant's input box.`,
    'You watch the work and now and then say one short, warm or wry line.',
    `Reply with one line in ${language}, at most ${language === 'English' ? '12 words' : '24 characters'}.`,
    'No advice, no instructions, no emoji, no quotes, no markdown. Never repeat a recent line.'
  ].join(' ')
  const user = [
    REASON_HINTS[request.reason],
    request.recent.length ? `Your recent lines: ${request.recent.join(' / ')}` : '',
    request.context ? `Latest exchange:\n${request.context}` : ''
  ].filter(Boolean).join('\n\n')
  return [{ role: 'system', content: system }, { role: 'user', content: user }]
}

export function cleanPetReactionLine(raw: unknown): string | null {
  if (typeof raw !== 'string') return null
  const line = raw
    .replace(/<think>[\s\S]*?<\/think>/gi, '')
    .split('\n')
    .map((part) => part.trim())
    .find(Boolean)
    ?.replace(/^["'“”「『]+|["'“”」』]+$/g, '')
    .trim()
  if (!line) return null
  return line.length > MAX_LINE_CHARS ? `${line.slice(0, MAX_LINE_CHARS - 1)}…` : line
}

export async function requestPetReaction(
  settings: AppSettingsV1,
  request: PetReactionRequest
): Promise<PetReactionResult> {
  const target = pickPetReactionModel(settings)
  if (!target) return { ok: false, message: 'No API key for the default model provider.' }
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), TIMEOUT_MS)
  try {
    const response = await fetch(buildEndpointProbeUrl('openai', target.baseUrl), {
      method: 'POST',
      headers: { Authorization: `Bearer ${target.apiKey}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model: target.model,
        messages: buildPetReactionMessages(request),
        max_tokens: MAX_TOKENS,
        temperature: 1,
        stream: false
      }),
      signal: controller.signal
    })
    if (!response.ok) return { ok: false, message: `HTTP ${response.status}` }
    const body = await response.json() as { choices?: Array<{ message?: { content?: unknown } }> }
    const text = cleanPetReactionLine(body.choices?.[0]?.message?.content)
    return text ? { ok: true, text } : { ok: false, message: 'Empty reply.' }
  } catch (error) {
    return { ok: false, message: error instanceof Error ? error.message : String(error) }
  } finally {
    clearTimeout(timeout)
  }
}
