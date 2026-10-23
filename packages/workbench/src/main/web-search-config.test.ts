import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defaultWebSearchSettings, mergeWebSearchSettings, enabledWebSearchProviderIds } from '../shared/app-settings'
import { parseWebSearchFromConfigToml, writeWebSearchConfigFile } from './web-search-config'

vi.mock('node:fs/promises', () => ({ readFile: vi.fn(), writeFile: vi.fn() }))
vi.mock('./deepseek-paths', () => ({ resolveDeepseekConfigPath: () => '/tmp/test-web-config.toml' }))
import { readFile, writeFile } from 'node:fs/promises'

beforeEach(() => { vi.clearAllMocks() })

describe('DeepSeek web tools settings', () => {
  it('keeps defaults and persists the shared provider order', () => {
    const defaults = defaultWebSearchSettings()
    expect(enabledWebSearchProviderIds(defaults)).toEqual(['anysearch'])
    const edited = mergeWebSearchSettings(defaults, {
      order: ['deepseek', 'anysearch', 'tavily'],
      providers: { deepseek: { enabled: true, apiKey: ' sk-test ' } }
    })
    expect(edited.providers.deepseek.apiKey).toBe('sk-test')
    expect(enabledWebSearchProviderIds(edited)).toEqual(['deepseek', 'anysearch'])
  })

  it('round-trips search backends, the shared key, and shared order through TOML', async () => {
    vi.mocked(readFile).mockResolvedValue('# Existing config\nmodel = "example"\n')
    const settings = mergeWebSearchSettings(defaultWebSearchSettings(), {
      order: ['deepseek', 'anysearch', 'tavily'],
      providers: { deepseek: { enabled: true, apiKey: 'sk-test' } }
    })
    await writeWebSearchConfigFile(settings)
    const written = String(vi.mocked(writeFile).mock.calls[0][1])
    expect(written).toContain('model = "example"')
    expect(parseWebSearchFromConfigToml(written).settings).toEqual(settings)
  })

  it('ignores the obsolete fetch override and respects enabled services', () => {
    const parsed = parseWebSearchFromConfigToml(
      'deepseek_tools_api_key = "sk-test"\nweb_fetch_provider = "deepseek"\nweb_search_providers = ["anysearch"]\n'
    ).settings
    expect(enabledWebSearchProviderIds(parsed)).toEqual(['anysearch'])
    expect(parsed.providers.deepseek).toEqual({ enabled: false, apiKey: 'sk-test' })
  })
})
