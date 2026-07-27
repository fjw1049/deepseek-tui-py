import { DEFAULT_ASR_MODEL } from '../../shared/app-settings'
import { resolveAsrTranscriptionEndpoint } from '../../shared/asr-config'
import { buildSilentWavProbeBytes } from '../../shared/asr-probe-wav'

export type TranscribeAudioInput = {
  apiKey: string
  model: string
  baseUrl?: string
  audio: Buffer
  fileName: string
  mimeType: string
}

export type TranscribeAudioResult =
  | { ok: true; text: string }
  | { ok: false; message: string }

export type ProbeAsrResult =
  | { ok: true; model: string; latencyMs: number; message: string }
  | { ok: false; model: string; latencyMs: number; message: string }

export function buildSilentWavProbe(durationMs = 100, sampleRate = 16_000): Buffer {
  return Buffer.from(buildSilentWavProbeBytes(durationMs, sampleRate))
}

type ApiErrorPayload = {
  text?: string
  error?: { message?: string } | string
  message?: string
  status?: number
  path?: string
}

function formatTranscriptionFailure(status: number, bodyText: string, payload: ApiErrorPayload | null): string {
  const nested = payload?.error
  if (typeof nested === 'object' && nested?.message?.trim()) {
    return nested.message.trim()
  }
  if (typeof payload?.message === 'string' && payload.message.trim()) {
    return payload.message.trim()
  }
  const errorLabel = typeof nested === 'string' ? nested : payload?.error
  if (typeof errorLabel === 'string' && errorLabel.trim() && payload?.status) {
    return `语音识别失败 (${payload.status} ${errorLabel.trim()})`
  }
  if (bodyText.trim().startsWith('{')) {
    return `语音识别失败 (${status})`
  }
  const trimmed = bodyText.trim()
  if (trimmed) {
    return trimmed.length > 160 ? `语音识别失败 (${status})` : trimmed
  }
  return `语音识别失败 (${status})`
}

export async function transcribeAudio(input: TranscribeAudioInput): Promise<TranscribeAudioResult> {
  const apiKey = input.apiKey.trim()
  if (!apiKey) {
    return { ok: false, message: 'ASR API key is not configured.' }
  }
  if (!input.audio.length) {
    return { ok: false, message: 'Recording is empty.' }
  }

  const endpoint = resolveAsrTranscriptionEndpoint(input.baseUrl)

  const form = new FormData()
  form.append('model', input.model.trim() || 'glm-asr-2512')
  form.append('stream', 'false')
  form.append('file', new Blob([input.audio], { type: input.mimeType }), input.fileName)

  let response: Response
  try {
    response = await fetch(endpoint, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${apiKey}`
      },
      body: form
    })
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    return { ok: false, message }
  }

  const bodyText = await response.text()
  let payload: ApiErrorPayload | null = null
  try {
    payload = JSON.parse(bodyText) as ApiErrorPayload
  } catch {
    payload = null
  }

  if (!response.ok) {
    return { ok: false, message: formatTranscriptionFailure(response.status, bodyText, payload) }
  }

  const text = payload?.text?.trim() ?? ''
  if (!text) {
    return { ok: false, message: 'No speech detected in the recording.' }
  }

  return { ok: true, text }
}

/**
 * Probe ASR credentials by posting a tiny silent WAV.
 * HTTP 200 means the key / model / endpoint are accepted (empty transcript is fine).
 */
export async function probeAsrEndpoint(input: {
  apiKey: string
  model: string
  baseUrl?: string
}): Promise<ProbeAsrResult> {
  const model = input.model.trim() || DEFAULT_ASR_MODEL
  const start = Date.now()
  const result = await transcribeAudio({
    apiKey: input.apiKey,
    model,
    baseUrl: input.baseUrl,
    audio: buildSilentWavProbe(),
    fileName: 'asr-probe.wav',
    mimeType: 'audio/wav'
  })
  const latencyMs = Date.now() - start
  if (result.ok) {
    return {
      ok: true,
      model,
      latencyMs,
      message: `ASR ok (${latencyMs}ms)`
    }
  }
  // Empty/silent audio still proves auth + model acceptance when the API returns 200.
  if (result.message === 'No speech detected in the recording.') {
    return {
      ok: true,
      model,
      latencyMs,
      message: `ASR endpoint accepted the probe (${latencyMs}ms)`
    }
  }
  return {
    ok: false,
    model,
    latencyMs,
    message: result.message
  }
}
