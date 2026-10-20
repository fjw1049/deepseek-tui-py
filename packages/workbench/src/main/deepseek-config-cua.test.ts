import { mkdtemp, readFile, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, expect, it } from 'vitest'
import { JsonSettingsStore } from './settings-store'
import { deepseekTuiConfigChanged, syncDeepseekTuiConfig } from './deepseek-config'

const originalHome = process.env.DEEPSEEK_HOME
afterEach(() => {
  if (originalHome === undefined) delete process.env.DEEPSEEK_HOME
  else process.env.DEEPSEEK_HOME = originalHome
})
it('writes explicit CUA choices and preserves installation and unrelated settings', async () => {
  const home = await mkdtemp(join(tmpdir(), 'ds-cua-config-'))
  process.env.DEEPSEEK_HOME = home
  const config = join(home, 'config.toml')
  await writeFile(config, 'api_key = "untouched"\n[cua]\ninstallation = "/custom/lcu/current"\n')
  const previous = await new JsonSettingsStore({ home }).load()
  const next = { ...previous, cuaEnabled: true, cuaChrome: true }
  expect(deepseekTuiConfigChanged(previous, next)).toBe(true)
  await syncDeepseekTuiConfig(next, previous)
  let text = await readFile(config, 'utf8')
  expect(text).toContain('enabled = true')
  expect(text).toContain('chrome = true')
  expect(text).toContain('installation = "/custom/lcu/current"')
  expect(text).toContain('api_key = "untouched"')
  await syncDeepseekTuiConfig({ ...next, cuaEnabled: false }, next)
  text = await readFile(config, 'utf8')
  expect(text).toContain('enabled = false')
})
