import { describe, expect, it } from 'vitest'
import { upsertTomlSections } from './toml-section'

describe('upsertTomlSections', () => {
  it('writes typed values into nested sections', () => {
    const next = upsertTomlSections(
      '[memory]\nenabled = false\nmode = "manual"\n',
      {
        memory: {
          enabled: true,
          mode: 'hybrid'
        },
        'memory.smart': {
          enabled: true,
          recall_limit: 8,
          recall_score_threshold: 0.3,
          capture_enabled: false
        }
      }
    )

    expect(next).toContain('[memory]')
    expect(next).toContain('enabled = true')
    expect(next).toContain('mode = "hybrid"')
    expect(next).toContain('[memory.smart]')
    expect(next).toContain('recall_limit = 8')
    expect(next).toContain('recall_score_threshold = 0.3')
    expect(next).toContain('capture_enabled = false')
  })

  it('writes per-model context windows with quoted model-id keys', () => {
    // Mirrors syncCustomEndpointConfig: model ids like "glm-5.2" contain
    // characters invalid in TOML bare keys, so they are pre-quoted.
    const next = upsertTomlSections('', {
      'providers.hs': {
        protocol: 'openai',
        base_url: 'https://api.example.com/v1',
        api_key: 'k',
        model: 'glm-5.2'
      },
      'providers.hs.context_windows': {
        '"glm-5.2"': 1_000_000,
        '"glm-5.2-air"': 300_000
      }
    })

    expect(next).toContain('[providers.hs.context_windows]')
    expect(next).toContain('"glm-5.2" = 1000000')
    expect(next).toContain('"glm-5.2-air" = 300000')
  })
})
