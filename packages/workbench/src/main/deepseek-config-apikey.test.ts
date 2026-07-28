import { describe, expect, it } from 'vitest'
import { readTopLevelApiKeyFromToml } from './deepseek-config'

describe('readTopLevelApiKeyFromToml', () => {
  it('reads top-level api_key', () => {
    const toml = `api_key = "sk-chat-abc"\nmodel = "deepseek-chat"\n\n[asr]\napi_key = "sk-asr-xyz"\n`
    expect(readTopLevelApiKeyFromToml(toml)).toBe('sk-chat-abc')
  })

  it('ignores [asr] api_key when top-level is missing', () => {
    const toml = `[asr]\napi_key = "sk-asr-xyz"\nmodel = "glm-asr"\n`
    expect(readTopLevelApiKeyFromToml(toml)).toBe('')
  })
})
