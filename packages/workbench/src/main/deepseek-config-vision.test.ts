import { mkdtemp, readFile, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import type { AppSettingsV1 } from '../shared/app-settings'
import { defaultLlmProviders } from '../shared/llm-providers'
import { deepseekTuiConfigChanged, syncDeepseekTuiConfig } from './deepseek-config'

describe('vision helper settings', () => {
  const previousHome = process.env.DEEPSEEK_HOME
  afterEach(() => {
    if (previousHome === undefined) delete process.env.DEEPSEEK_HOME
    else process.env.DEEPSEEK_HOME = previousHome
  })
  it('syncs selection and explicit removal while preserving credentials', async () => {
    const home = await mkdtemp(join(tmpdir(), 'ds-vision-config-'))
    process.env.DEEPSEEK_HOME = home
    await writeFile(join(home, 'config.toml'), 'api_key = "unchanged"\n[vision]\ntimeout_seconds = 42\n')
    const previous = {
      deepseek: { apiKey: '', baseUrl: '', approvalPolicy: 'auto', sandboxMode: 'workspace-write' },
      defaultLlmProviderId: 'deepseek', llmProviders: defaultLlmProviders(), customEndpoints: [], locale: 'zh'
    } as AppSettingsV1
    const next = { ...previous, visionModel: 'visual::image-model' }
    expect(deepseekTuiConfigChanged(previous, next)).toBe(true)
    await syncDeepseekTuiConfig(next, previous)
    let content = await readFile(join(home, 'config.toml'), 'utf8')
    expect(content).toContain('model = "visual::image-model"')
    expect(content).toContain('timeout_seconds = 42')
    expect(content).toContain('api_key = "unchanged"')
    await syncDeepseekTuiConfig({ ...next, visionModel: '' }, next)
    content = await readFile(join(home, 'config.toml'), 'utf8')
    expect(content).toContain('model = ""')
    expect(content).not.toContain('visual::image-model')
  })
})
