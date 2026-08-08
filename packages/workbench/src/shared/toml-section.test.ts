import { describe, expect, it } from 'vitest'
import {
  readTomlBool,
  readTomlTopLevelString,
  readTomlTopLevelStringArray,
  upsertTomlSections,
  upsertTomlTopLevel
} from './toml-section'

describe('readTomlBool', () => {
  it('reads section booleans and ignores missing keys', () => {
    const toml = '[features]\nautomations = true\ntasks = false\n'
    expect(readTomlBool(toml, 'automations', { section: 'features' })).toBe(true)
    expect(readTomlBool(toml, 'tasks', { section: 'features' })).toBe(false)
    expect(readTomlBool(toml, 'mcp', { section: 'features' })).toBeNull()
  })
})

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

  it('upserts ui.locale for reply-language sync', () => {
    const next = upsertTomlSections(
      '[ui]\ncolor_scheme = "default"\nshow_thinking = true\n',
      { ui: { locale: 'en' } }
    )
    expect(next).toContain('[ui]')
    expect(next).toContain('locale = "en"')
    expect(next).toContain('color_scheme = "default"')
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

describe('upsertTomlTopLevel', () => {
  it('writes and reads web search top-level keys without touching sections', () => {
    const next = upsertTomlTopLevel(
      'api_key = "sk-chat"\n\n[asr]\napi_key = "sk-asr"\n',
      {
        anysearch_api_key: 'as-key',
        tavily_api_key: 'tv-key',
        web_search_providers: ['anysearch', 'tavily']
      }
    )

    expect(readTomlTopLevelString(next, 'api_key')).toBe('sk-chat')
    expect(readTomlTopLevelString(next, 'anysearch_api_key')).toBe('as-key')
    expect(readTomlTopLevelString(next, 'tavily_api_key')).toBe('tv-key')
    expect(readTomlTopLevelStringArray(next, 'web_search_providers')).toEqual([
      'anysearch',
      'tavily'
    ])
    expect(next).toContain('[asr]')
    expect(next).toContain('api_key = "sk-asr"')
  })

  it('removes top-level keys when value is null', () => {
    const next = upsertTomlTopLevel(
      'tavily_api_key = "tv"\nweb_search_providers = ["tavily"]\n\n[ui]\nlocale = "zh"\n',
      {
        tavily_api_key: null,
        web_search_providers: ['anysearch']
      }
    )
    expect(readTomlTopLevelString(next, 'tavily_api_key')).toBeNull()
    expect(readTomlTopLevelStringArray(next, 'web_search_providers')).toEqual(['anysearch'])
    expect(next).toContain('[ui]')
  })
})
