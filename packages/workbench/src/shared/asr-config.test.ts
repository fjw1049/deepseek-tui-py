import { describe, expect, it } from 'vitest'
import { resolveAsrTranscriptionEndpoint, normalizeAsrBaseUrlForDisplay } from './asr-config'

describe('resolveAsrTranscriptionEndpoint', () => {
  it('appends /audio/transcriptions to the default base URL', () => {
    expect(resolveAsrTranscriptionEndpoint()).toBe(
      'https://open.bigmodel.cn/api/paas/v4/audio/transcriptions'
    )
  })

  it('normalizes trailing slashes on base URLs', () => {
    expect(resolveAsrTranscriptionEndpoint('https://open.bigmodel.cn/api/paas/v4/')).toBe(
      'https://open.bigmodel.cn/api/paas/v4/audio/transcriptions'
    )
  })

  it('keeps legacy full endpoint URLs unchanged', () => {
    expect(
      resolveAsrTranscriptionEndpoint('https://open.bigmodel.cn/api/paas/v4/audio/transcriptions')
    ).toBe('https://open.bigmodel.cn/api/paas/v4/audio/transcriptions')
  })
})

describe('normalizeAsrBaseUrlForDisplay', () => {
  it('strips /audio/transcriptions for settings display', () => {
    expect(
      normalizeAsrBaseUrlForDisplay('https://open.bigmodel.cn/api/paas/v4/audio/transcriptions')
    ).toBe('https://open.bigmodel.cn/api/paas/v4')
  })

  it('returns the default base URL when unset', () => {
    expect(normalizeAsrBaseUrlForDisplay()).toBe('https://open.bigmodel.cn/api/paas/v4')
  })

  it('replaces misconfigured DeepSeek LLM URLs with the BigModel default', () => {
    expect(normalizeAsrBaseUrlForDisplay('https://api.deepseek.com')).toBe(
      'https://open.bigmodel.cn/api/paas/v4'
    )
    expect(normalizeAsrBaseUrlForDisplay('https://api.deepseek.com/beta')).toBe(
      'https://open.bigmodel.cn/api/paas/v4'
    )
  })
})
