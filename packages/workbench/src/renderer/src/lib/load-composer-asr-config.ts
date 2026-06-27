import { type AsrSettingsV1 } from '@shared/app-settings'

export async function loadComposerAsrConfig(): Promise<AsrSettingsV1 | null> {
  if (typeof window.dsGui === 'undefined') return null
  if (typeof window.dsGui.getAsrConfig !== 'function') return null
  const result = await window.dsGui.getAsrConfig()
  return result.config
}

export function isComposerVoiceBridgeReady(): boolean {
  return typeof window.dsGui !== 'undefined' && typeof window.dsGui.transcribeAudio === 'function'
}

export function isMediaCaptureSupported(): boolean {
  return (
    typeof navigator !== 'undefined' &&
    !!navigator.mediaDevices?.getUserMedia &&
    typeof MediaRecorder !== 'undefined'
  )
}
