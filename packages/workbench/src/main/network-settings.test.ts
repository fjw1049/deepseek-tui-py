import { mkdir, mkdtemp, readFile, readdir, rm, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { expect, it, vi } from 'vitest'
import { writeNetworkSettings } from './network-settings'
import { JsonSettingsStore } from './settings-store'
import { resolveWorkbenchSettingsPath } from '../shared/workbench-home'

it('publishes a complete policy file and allows removing every bypass', async () => {
  const home = await mkdtemp(join(tmpdir(), 'network-settings-'))
  vi.stubEnv('DEEPSEEK_HOME', home)
  try {
    await writeNetworkSettings({ mode: 'system', bypassHosts: [' INTERNAL.EXAMPLE '] })
    expect(JSON.parse(await readFile(join(home, 'network.json'), 'utf8')))
      .toEqual({ mode: 'system', bypassHosts: ['internal.example'] })
    await writeNetworkSettings({ mode: 'direct', bypassHosts: [] })
    expect(JSON.parse(await readFile(join(home, 'network.json'), 'utf8')))
      .toEqual({ mode: 'direct', bypassHosts: [] })
    expect(await readdir(home)).toEqual(['network.json'])
  } finally {
    vi.unstubAllEnvs()
    await rm(home, { recursive: true, force: true })
  }
})

it('migrates the legacy bypass once and persists an explicitly cleared list', async () => {
  const home = await mkdtemp(join(tmpdir(), 'network-migration-'))
  try {
    const path = resolveWorkbenchSettingsPath(home)
    await mkdir(join(path, '..'), { recursive: true })
    await writeFile(path, JSON.stringify({
      workspaceRoot: join(home, 'workspace'),
      customEndpoints: [{ id: 'za', name: 'ZA', baseUrl: 'http://devpilot.zhonganonline.com/api', models: [] }]
    }))
    const store = new JsonSettingsStore({ home })
    expect((await store.load()).network?.bypassHosts).toEqual(['devpilot.zhonganonline.com'])
    await store.patch({ network: { mode: 'system', bypassHosts: [] } })
    expect((await new JsonSettingsStore({ home }).load()).network)
      .toEqual({ mode: 'system', bypassHosts: [] })
  } finally {
    await rm(home, { recursive: true, force: true })
  }
})
