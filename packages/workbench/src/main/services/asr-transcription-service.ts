const ASR_ENDPOINT = 'https://open.bigmodel.cn/api/paas/v4/audio/transcriptions'

export type TranscribeAudioInput = {
  apiKey: string
  model: string
  audio: Buffer
  fileName: string
  mimeType: string
}

export type TranscribeAudioResult =
  | { ok: true; text: string }
  | { ok: false; message: string }

export async function transcribeAudio(input: TranscribeAudioInput): Promise<TranscribeAudioResult> {
  const apiKey = input.apiKey.trim()
  if (!apiKey) {
    return { ok: false, message: 'ASR API key is not configured.' }
  }
  if (!input.audio.length) {
    return { ok: false, message: 'Recording is empty.' }
  }

  const form = new FormData()
  form.append('model', input.model.trim() || 'glm-asr-2512')
  form.append('stream', 'false')
  form.append('file', new Blob([input.audio], { type: input.mimeType }), input.fileName)

  let response: Response
  try {
    response = await fetch(ASR_ENDPOINT, {
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
  let payload: { text?: string; error?: { message?: string } } | null = null
  try {
    payload = JSON.parse(bodyText) as { text?: string; error?: { message?: string } }
  } catch {
    payload = null
  }

  if (!response.ok) {
    const message =
      payload?.error?.message?.trim() ||
      bodyText.trim() ||
      `Transcription failed (${response.status}).`
    return { ok: false, message }
  }

  const text = payload?.text?.trim() ?? ''
  if (!text) {
    return { ok: false, message: 'No speech detected in the recording.' }
  }

  return { ok: true, text }
}
