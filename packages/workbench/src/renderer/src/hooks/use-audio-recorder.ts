import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

const BAR_COUNT = 150
const DEFAULT_MAX_DURATION_MS = 30_000
const SAMPLE_INTERVAL_MS = 60
const SCRIPT_PROCESSOR_BUFFER_SIZE = 4096
const TARGET_SAMPLE_RATE = 16_000
const LEVEL_NOISE_FLOOR = 0.012
const LEVEL_GAIN = 11
const LEVEL_CURVE = 0.78
const LEVEL_SMOOTHING = 0.45

function emptyLevels(): number[] {
  return Array.from({ length: BAR_COUNT }, () => 0)
}

function extensionForMimeType(mimeType: string): string {
  if (mimeType.includes('webm')) return 'webm'
  if (mimeType.includes('mp4')) return 'm4a'
  if (mimeType.includes('ogg')) return 'ogg'
  if (mimeType.includes('wav')) return 'wav'
  return 'audio'
}

function mergeFloat32(chunks: Float32Array[]): Float32Array {
  let total = 0
  for (const chunk of chunks) total += chunk.length
  const out = new Float32Array(total)
  let offset = 0
  for (const chunk of chunks) {
    out.set(chunk, offset)
    offset += chunk.length
  }
  return out
}

// Linear resampling without anti-aliasing — sufficient for 48k→16k speech ASR input.
function resampleTo(input: Float32Array, inputRate: number, targetRate: number): Float32Array {
  if (inputRate === targetRate || input.length === 0) return input
  const ratio = inputRate / targetRate
  const outLength = Math.max(1, Math.floor(input.length / ratio))
  const out = new Float32Array(outLength)
  for (let i = 0; i < outLength; i += 1) {
    const srcIndex = i * ratio
    const left = Math.floor(srcIndex)
    const right = Math.min(left + 1, input.length - 1)
    const frac = srcIndex - left
    out[i] = input[left] * (1 - frac) + input[right] * frac
  }
  return out
}

function encodeWavPcm(samples: Float32Array, sampleRate: number): ArrayBuffer {
  const byteLength = 44 + samples.length * 2
  const buffer = new ArrayBuffer(byteLength)
  const view = new DataView(buffer)
  const writeString = (offset: number, text: string): void => {
    for (let i = 0; i < text.length; i += 1) {
      view.setUint8(offset + i, text.charCodeAt(i))
    }
  }

  writeString(0, 'RIFF')
  view.setUint32(4, 36 + samples.length * 2, true)
  writeString(8, 'WAVE')
  writeString(12, 'fmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true)
  view.setUint16(22, 1, true)
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * 2, true)
  view.setUint16(32, 2, true)
  view.setUint16(34, 16, true)
  writeString(36, 'data')
  view.setUint32(40, samples.length * 2, true)

  let offset = 44
  for (let i = 0; i < samples.length; i += 1) {
    const clamped = Math.max(-1, Math.min(1, samples[i]))
    view.setInt16(offset, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true)
    offset += 2
  }
  return buffer
}

function encodeRecordedWav(
  chunks: Float32Array[],
  sourceSampleRate: number
): { blob: Blob; durationMs: number } | null {
  if (!chunks.length) return null
  const merged = mergeFloat32(chunks)
  if (!merged.length) return null
  const resampled = resampleTo(merged, sourceSampleRate, TARGET_SAMPLE_RATE)
  const wav = encodeWavPcm(resampled, TARGET_SAMPLE_RATE)
  const durationMs = Math.round((merged.length / sourceSampleRate) * 1000)
  return { blob: new Blob([wav], { type: 'audio/wav' }), durationMs }
}

export type RecordedAudio = {
  blob: Blob
  mimeType: string
  fileName: string
  durationMs: number
}

export type RecorderStartResult =
  | { ok: true }
  | { ok: false; reason: 'unsupported' | 'denied' | 'unavailable' }

export function useAudioRecorder(options?: {
  maxDurationMs?: number
  onAutoStop?: (audio: RecordedAudio | null) => void
}): {
  supported: boolean
  recording: boolean
  levels: number[]
  elapsedMs: number
  maxDurationMs: number
  start: () => Promise<RecorderStartResult>
  stop: () => Promise<RecordedAudio | null>
  cancel: () => void
} {
  const maxDurationMs = options?.maxDurationMs ?? DEFAULT_MAX_DURATION_MS
  const onAutoStopRef = useRef(options?.onAutoStop)
  onAutoStopRef.current = options?.onAutoStop

  const [supported] = useState(
    () =>
      typeof navigator !== 'undefined' &&
      !!navigator.mediaDevices?.getUserMedia &&
      typeof AudioContext !== 'undefined'
  )
  const [recording, setRecording] = useState(false)
  const [levels, setLevels] = useState<number[]>(emptyLevels)
  const [elapsedMs, setElapsedMs] = useState(0)

  const streamRef = useRef<MediaStream | null>(null)
  const audioContextRef = useRef<AudioContext | null>(null)
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null)
  const scriptNodeRef = useRef<ScriptProcessorNode | null>(null)
  const silencerRef = useRef<GainNode | null>(null)
  const analyserRef = useRef<AnalyserNode | null>(null)
  const levelsRef = useRef<number[]>(emptyLevels())
  const pcmChunksRef = useRef<Float32Array[]>([])
  const sourceSampleRateRef = useRef(0)
  const rafRef = useRef<number | null>(null)
  const lastLevelsAtRef = useRef(0)
  const startedAtRef = useRef(0)
  const timerRef = useRef<number | null>(null)
  const autoStopRef = useRef<(() => void) | null>(null)
  const stopResolveRef = useRef<((audio: RecordedAudio | null) => void) | null>(null)

  const cleanupStream = useCallback(() => {
    if (rafRef.current != null) {
      window.cancelAnimationFrame(rafRef.current)
      rafRef.current = null
    }
    if (timerRef.current != null) {
      window.clearInterval(timerRef.current)
      timerRef.current = null
    }
    analyserRef.current = null
    if (scriptNodeRef.current) {
      scriptNodeRef.current.onaudioprocess = null
      try {
        scriptNodeRef.current.disconnect()
      } catch {
        /* ignore */
      }
      scriptNodeRef.current = null
    }
    if (sourceRef.current) {
      try {
        sourceRef.current.disconnect()
      } catch {
        /* ignore */
      }
      sourceRef.current = null
    }
    if (silencerRef.current) {
      try {
        silencerRef.current.disconnect()
      } catch {
        /* ignore */
      }
      silencerRef.current = null
    }
    if (audioContextRef.current) {
      void audioContextRef.current.close()
      audioContextRef.current = null
    }
    if (streamRef.current) {
      for (const track of streamRef.current.getTracks()) track.stop()
      streamRef.current = null
    }
    pcmChunksRef.current = []
    sourceSampleRateRef.current = 0
    startedAtRef.current = 0
    stopResolveRef.current = null
    levelsRef.current = emptyLevels()
    setLevels((prev) => (prev.every((value) => value === 0) ? prev : emptyLevels()))
    setElapsedMs((prev) => (prev === 0 ? prev : 0))
    setRecording((prev) => (prev ? false : prev))
  }, [])

  const cancel = useCallback(() => {
    stopResolveRef.current = null
    cleanupStream()
  }, [cleanupStream])

  const stop = useCallback((): Promise<RecordedAudio | null> => {
    const startedAt = startedAtRef.current
    const audioContext = audioContextRef.current
    if (!startedAt || !audioContext) {
      cleanupStream()
      return Promise.resolve(null)
    }

    return new Promise((resolve) => {
      stopResolveRef.current = resolve
      const sourceRate = sourceSampleRateRef.current || audioContext.sampleRate
      const chunks = pcmChunksRef.current
      // Capture the analyser-free cleanup path: encode after the current JS turn so
      // any in-flight onaudioprocess callbacks still flush into chunks first.
      const finalize = (): void => {
        const encoded = encodeRecordedWav(chunks, sourceRate)
        const fallbackDuration = Math.max(0, Date.now() - startedAt)
        cleanupStream()
        if (!encoded) {
          resolve(null)
          return
        }
        resolve({
          blob: encoded.blob,
          mimeType: 'audio/wav',
          fileName: `recording.${extensionForMimeType('audio/wav')}`,
          durationMs: encoded.durationMs || fallbackDuration
        })
      }
      // Defer one tick so the last onaudioprocess buffers can arrive.
      window.setTimeout(finalize, 0)
    })
  }, [cleanupStream])

  const start = useCallback(async (): Promise<RecorderStartResult> => {
    if (!supported || recording) return { ok: false, reason: 'unsupported' }
    cancel()

    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch (error) {
      const name = error instanceof DOMException ? error.name : ''
      const reason =
        name === 'NotAllowedError' || name === 'SecurityError' ? 'denied' : 'unavailable'
      return { ok: false, reason }
    }

    streamRef.current = stream
    pcmChunksRef.current = []
    startedAtRef.current = Date.now()
    setElapsedMs(0)
    setRecording(true)

    const audioContext = new AudioContext()
    audioContextRef.current = audioContext
    sourceSampleRateRef.current = audioContext.sampleRate

    const source = audioContext.createMediaStreamSource(stream)
    sourceRef.current = source

    const analyser = audioContext.createAnalyser()
    analyser.fftSize = 256
    analyser.smoothingTimeConstant = 0.82
    source.connect(analyser)
    analyserRef.current = analyser

    // ScriptProcessorNode only fires onaudioprocess when connected to destination.
    // Route through a zero-gain node so no audio is echoed back to the user.
    const scriptNode = audioContext.createScriptProcessor(SCRIPT_PROCESSOR_BUFFER_SIZE, 1, 1)
    scriptNodeRef.current = scriptNode
    scriptNode.onaudioprocess = (event) => {
      const input = event.inputBuffer.getChannelData(0)
      if (input.length) pcmChunksRef.current.push(new Float32Array(input))
    }
    const silencer = audioContext.createGain()
    silencer.gain.value = 0
    source.connect(scriptNode)
    scriptNode.connect(silencer)
    silencer.connect(audioContext.destination)
    silencerRef.current = silencer

    const timeData = new Uint8Array(analyser.fftSize)
    const tickLevels = (now: number): void => {
      if (!analyserRef.current) return
      if (now - lastLevelsAtRef.current >= SAMPLE_INTERVAL_MS) {
        lastLevelsAtRef.current = now
        analyserRef.current.getByteTimeDomainData(timeData)
        let sumSquares = 0
        for (let i = 0; i < timeData.length; i += 1) {
          const sample = (timeData[i] - 128) / 128
          sumSquares += sample * sample
        }
        const rms = Math.sqrt(sumSquares / timeData.length)
        const boosted = Math.max(0, (rms - LEVEL_NOISE_FLOOR) * LEVEL_GAIN)
        const target = Math.min(1, Math.pow(boosted, LEVEL_CURVE))
        const history = levelsRef.current
        const prev = history[history.length - 1] ?? 0
        const level = prev * (1 - LEVEL_SMOOTHING) + target * LEVEL_SMOOTHING
        history.shift()
        history.push(level)
        setLevels(history.slice())
      }
      rafRef.current = window.requestAnimationFrame(tickLevels)
    }
    lastLevelsAtRef.current = 0
    rafRef.current = window.requestAnimationFrame(tickLevels)

    timerRef.current = window.setInterval(() => {
      const nextElapsed = Date.now() - startedAtRef.current
      setElapsedMs(nextElapsed)
      if (nextElapsed >= maxDurationMs) {
        autoStopRef.current?.()
      }
    }, 200)

    return { ok: true }
  }, [cancel, maxDurationMs, recording, supported])

  autoStopRef.current = () => {
    void stop().then((audio) => onAutoStopRef.current?.(audio))
  }

  useEffect(() => () => cancel(), [cancel])

  return useMemo(
    () => ({
      supported,
      recording,
      levels,
      elapsedMs,
      maxDurationMs,
      start,
      stop,
      cancel
    }),
    [supported, recording, levels, elapsedMs, maxDurationMs, start, stop, cancel]
  )
}

export function joinSpeechText(base: string, chunk: string): string {
  const nextChunk = chunk.trim()
  if (!nextChunk) return base
  const trimmedBase = base.trimEnd()
  if (!trimmedBase) return nextChunk
  return `${trimmedBase} ${nextChunk}`
}

export function formatVoiceDuration(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000))
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return `${minutes}:${seconds.toString().padStart(2, '0')}`
}
