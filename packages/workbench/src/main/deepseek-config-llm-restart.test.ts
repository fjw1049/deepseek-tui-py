import { describe, expect, it } from 'vitest'
import type { AppSettingsV1 } from '../shared/app-settings'
import { defaultLlmProviders } from '../shared/llm-providers'
import { llmProviderConfigChanged } from './deepseek-config'

function baseSettings(): Pick<AppSettingsV1, 'defaultLlmProviderId' | 'llmProviders'> {
  return {
    defaultLlmProviderId: 'deepseek',
    llmProviders: defaultLlmProviders()
  }
}

describe('llmProviderConfigChanged', () => {
  it('detects builtin provider key / model / context window edits', () => {
    const prev = baseSettings()
    const next = {
      ...prev,
      llmProviders: {
        ...prev.llmProviders,
        'volcengine-ark': {
          ...prev.llmProviders['volcengine-ark'],
          apiKey: 'ark-test',
          models: [{ id: 'glm-5-2-260617', enabled: true, contextWindow: 500_000 }]
        }
      }
    }
    expect(llmProviderConfigChanged(prev as AppSettingsV1, next as AppSettingsV1)).toBe(true)
  })

  it('ignores unrelated provider-table identity', () => {
    const prev = baseSettings()
    const next = { ...prev, llmProviders: { ...prev.llmProviders } }
    expect(llmProviderConfigChanged(prev as AppSettingsV1, next as AppSettingsV1)).toBe(false)
  })
})
