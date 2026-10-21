import { mkdir, mkdtemp, readFile, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, expect, it } from 'vitest'
import { JsonSettingsStore } from './settings-store'
import { deepseekTuiConfigChanged, syncDeepseekTuiConfig, syncCuaConfig } from './deepseek-config'

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

it('automatically enables an installed runtime but preserves an explicit opt-out', async () => {
  const home = await mkdtemp(join(tmpdir(), 'ds-cua-auto-'))
  process.env.DEEPSEEK_HOME = home
  const installation = join(home, 'lcu')
  await mkdir(join(installation, 'bin'), { recursive: true })
  await mkdir(join(installation, 'adapters'))
  await writeFile(join(installation, 'node-path'), process.execPath)
  await writeFile(join(installation, 'bin/lcu'), 'fixture')
  const config = join(home, 'config.toml')
  const content = `[cua]\ninstallation = "${installation}"\n`
  await writeFile(config, content)
  const settings = await new JsonSettingsStore({ home }).load()
  // An incomplete installation must not enable desktop tools.
  await syncCuaConfig(settings)
  expect(await readFile(config, 'utf8')).toBe(content)
  await writeFile(join(installation, 'adapters/client.mjs'), 'fixture')
  await syncCuaConfig(settings)
  expect(await readFile(config, 'utf8')).toContain('enabled = true')
  await writeFile(config, content + 'enabled = false\n')
  await syncCuaConfig(settings)
  expect(await readFile(config, 'utf8')).toContain('enabled = false')
  await writeFile(config, content)
  await syncCuaConfig({ ...settings, cuaEnabled: false })
  expect(await readFile(config, 'utf8')).toContain('enabled = false')
})
