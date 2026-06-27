import { DEFAULT_ASR_MODEL, type AsrSettingsV1 } from './app-settings'
import { readTomlString } from './toml-section'

export function parseAsrSettingsFromToml(content: string): AsrSettingsV1 {
  return {
    apiKey: readTomlString(content, 'api_key', { section: 'asr' }) ?? '',
    model: readTomlString(content, 'model', { section: 'asr' }) ?? DEFAULT_ASR_MODEL
  }
}
