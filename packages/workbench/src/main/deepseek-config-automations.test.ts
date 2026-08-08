import { mkdtemp, readFile, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import { ensureAutomationsFeatureEnabled } from './deepseek-config'

describe('ensureAutomationsFeatureEnabled', () => {
  const previousHome = process.env.DEEPSEEK_HOME

  afterEach(() => {
    if (previousHome === undefined) delete process.env.DEEPSEEK_HOME
    else process.env.DEEPSEEK_HOME = previousHome
  })

  it('writes features.automations and tasks when missing', async () => {
    const home = await mkdtemp(join(tmpdir(), 'ds-gui-auto-feat-'))
    process.env.DEEPSEEK_HOME = home
    await writeFile(join(home, 'config.toml'), 'api_key = "sk-test"\n', 'utf8')

    const first = await ensureAutomationsFeatureEnabled()
    expect(first.changed).toBe(true)
    const body = await readFile(join(home, 'config.toml'), 'utf8')
    expect(body).toContain('[features]')
    expect(body).toContain('automations = true')
    expect(body).toContain('tasks = true')

    const second = await ensureAutomationsFeatureEnabled()
    expect(second.changed).toBe(false)
  })

  it('rewrites when tasks is explicitly false', async () => {
    const home = await mkdtemp(join(tmpdir(), 'ds-gui-auto-feat-'))
    process.env.DEEPSEEK_HOME = home
    await writeFile(
      join(home, 'config.toml'),
      '[features]\nautomations = true\ntasks = false\n',
      'utf8'
    )

    const result = await ensureAutomationsFeatureEnabled()
    expect(result.changed).toBe(true)
    const body = await readFile(join(home, 'config.toml'), 'utf8')
    expect(body).toContain('automations = true')
    expect(body).toContain('tasks = true')
    expect(body).not.toContain('tasks = false')
  })
})
