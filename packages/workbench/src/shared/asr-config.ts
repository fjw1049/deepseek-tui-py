import { DEFAULT_ASR_BASE_URL, DEFAULT_ASR_MODEL, type AsrSettingsV1 } from './app-settings'
import { readTomlString } from './toml-section'

const ASR_TRANSCRIPTIONS_SUFFIX = '/audio/transcriptions'

/** Resolve a stored base URL (or legacy full endpoint) to the transcription POST URL. */
export function resolveAsrTranscriptionEndpoint(baseUrl?: string | null): string {
  const trimmed = (baseUrl?.trim() || DEFAULT_ASR_BASE_URL).replace(/\/+$/, '')
  if (trimmed.endsWith(ASR_TRANSCRIPTIONS_SUFFIX)) return trimmed
  return `${trimmed}${ASR_TRANSCRIPTIONS_SUFFIX}`
}

/** LLM endpoints accidentally saved under [asr] — ASR should use BigModel instead. */
export function isMisconfiguredAsrBaseUrl(baseUrl?: string | null): boolean {
  const trimmed = baseUrl?.trim().replace(/\/+$/, '').toLowerCase() ?? ''
  if (!trimmed) return false
  return trimmed.includes('deepseek.com')
}

/** Normalize stored base/full endpoint URLs for UI display. */
export function normalizeAsrBaseUrlForDisplay(baseUrl?: string | null): string {
  const trimmed = (baseUrl?.trim() || '').replace(/\/+$/, '')
  if (!trimmed || isMisconfiguredAsrBaseUrl(trimmed)) {
    return DEFAULT_ASR_BASE_URL.replace(/\/+$/, '')
  }
  if (trimmed.endsWith(ASR_TRANSCRIPTIONS_SUFFIX)) {
    const base = trimmed.slice(0, -ASR_TRANSCRIPTIONS_SUFFIX.length).replace(/\/+$/, '')
    return base || DEFAULT_ASR_BASE_URL.replace(/\/+$/, '')
  }
  return trimmed
}

export function parseAsrSettingsFromToml(content: string): AsrSettingsV1 {
  const rawBaseUrl = readTomlString(content, 'base_url', { section: 'asr' })
  return {
    apiKey: readTomlString(content, 'api_key', { section: 'asr' }) ?? '',
    model: readTomlString(content, 'model', { section: 'asr' }) ?? DEFAULT_ASR_MODEL,
    baseUrl: normalizeAsrBaseUrlForDisplay(rawBaseUrl)
  }
}
