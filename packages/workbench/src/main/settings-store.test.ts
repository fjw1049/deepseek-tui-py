import { mkdir, mkdtemp, readFile, readdir, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { JsonSettingsStore } from './settings-store'
import {
  resolveClawChannelsRoot,
  resolveLegacyClawChannelsRoot,
  resolveWorkbenchSettingsPath
} from '../shared/workbench-home'

describe('JsonSettingsStore', () => {
  it('preserves deepseek.autoStart=false when loading saved settings', async () => {
    const home = await mkdtemp(join(tmpdir(), 'ds-gui-settings-'))
    const workspaceRoot = join(home, 'workspace')
    await mkdir(workspaceRoot, { recursive: true })
    const settingsPath = resolveWorkbenchSettingsPath(home)
    await mkdir(join(settingsPath, '..'), { recursive: true })

    await writeFile(
      settingsPath,
      JSON.stringify({
        version: 1,
        workspaceRoot,
        deepseek: {
          autoStart: false
        }
      }),
      'utf8'
    )

    const store = new JsonSettingsStore({ home })
    const loaded = await store.load()

    expect(loaded.deepseek.autoStart).toBe(false)
  })

  it('migrates legacy Electron userData settings into workbench/', async () => {
    const home = await mkdtemp(join(tmpdir(), 'ds-gui-home-'))
    const userDataDir = await mkdtemp(join(tmpdir(), 'ds-gui-userdata-'))
    const workspaceRoot = join(home, 'workspace')
    await mkdir(workspaceRoot, { recursive: true })

    await writeFile(
      join(userDataDir, 'deepseek-gui-settings.json'),
      JSON.stringify({
        version: 1,
        workspaceRoot,
        deepseek: { autoStart: false }
      }),
      'utf8'
    )

    const store = new JsonSettingsStore({ home, legacyUserDataPath: userDataDir })
    const loaded = await store.load()

    expect(loaded.deepseek.autoStart).toBe(false)
    expect(JSON.parse(await readFile(resolveWorkbenchSettingsPath(home), 'utf8')).deepseek.autoStart).toBe(
      false
    )
  })

  it('migrates claw even when workbench/claw was pre-created empty', async () => {
    const home = await mkdtemp(join(tmpdir(), 'ds-gui-claw-mig-'))
    const src = join(resolveLegacyClawChannelsRoot(home), 'feishu', 'demo')
    const dest = resolveClawChannelsRoot(home)
    await mkdir(src, { recursive: true })
    await writeFile(join(src, 'note.txt'), 'kept', 'utf8')
    await mkdir(dest, { recursive: true }) // empty placeholder like layout.py used to create

    const store = new JsonSettingsStore({ home })
    await store.load()
    expect(await readFile(join(dest, 'feishu', 'demo', 'note.txt'), 'utf8')).toBe('kept')
  })

  it('rewrites persisted legacy claw workspaceRoot on load', async () => {
    const home = await mkdtemp(join(tmpdir(), 'ds-gui-claw-rewrite-'))
    const legacyRoot = join(resolveLegacyClawChannelsRoot(home), 'feishu', 'feishu', 'cli_xxx')
    const settingsPath = resolveWorkbenchSettingsPath(home)
    await mkdir(join(settingsPath, '..'), { recursive: true })
    await writeFile(
      settingsPath,
      JSON.stringify({
        version: 1,
        workspaceRoot: join(home, 'workspace'),
        claw: {
          channels: [
            {
              id: 'ch1',
              provider: 'feishu',
              workspaceRoot: legacyRoot,
              platformCredential: {
                kind: 'feishu',
                domain: 'feishu',
                appId: 'cli_xxx',
                appSecret: 'secret',
                createdAt: '2026-01-01T00:00:00.000Z'
              }
            }
          ]
        }
      }),
      'utf8'
    )

    const store = new JsonSettingsStore({ home })
    const loaded = await store.load()
    expect(loaded.claw.channels[0]?.workspaceRoot).toBe(
      join(resolveClawChannelsRoot(home), 'feishu', 'feishu', 'cli_xxx')
    )
  })

  it('defaults claw channel workspaces under ~/.deepseek/workbench/claw', async () => {
    const home = await mkdtemp(join(tmpdir(), 'ds-gui-claw-'))
    const store = new JsonSettingsStore({ home })
    await store.load()
    const patched = await store.patch({
      claw: {
        channels: [
          {
            id: 'ch1',
            provider: 'feishu',
            platformCredential: {
              kind: 'feishu',
              domain: 'feishu',
              appId: 'cli_xxx',
              appSecret: 'secret',
              createdAt: '2026-01-01T00:00:00.000Z'
            },
            workspaceRoot: ''
          }
        ]
      }
    })
    expect(patched.claw.channels[0]?.workspaceRoot).toBe(
      join(resolveClawChannelsRoot(home), 'feishu', 'feishu', 'cli_xxx')
    )
  })

  it('loads and normalizes memory settings', async () => {
    const home = await mkdtemp(join(tmpdir(), 'ds-gui-settings-'))
    const workspaceRoot = join(home, 'workspace')
    await mkdir(workspaceRoot, { recursive: true })
    const settingsPath = resolveWorkbenchSettingsPath(home)
    await mkdir(join(settingsPath, '..'), { recursive: true })

    await writeFile(
      settingsPath,
      JSON.stringify({
        version: 1,
        workspaceRoot,
        memory: {
          enabled: true,
          mode: 'auto',
          smart: {
            enabled: true,
            recallLimit: 12,
            recallScoreThreshold: 0.5,
            dataDir: '~/custom-memory'
          }
        }
      }),
      'utf8'
    )

    const store = new JsonSettingsStore({ home })
    const loaded = await store.load()

    expect(loaded.memory.enabled).toBe(true)
    expect(loaded.memory.mode).toBe('auto')
    expect(loaded.memory.smart.enabled).toBe(true)
    expect(loaded.memory.smart.recallLimit).toBe(12)
    expect(loaded.memory.smart.recallScoreThreshold).toBe(0.5)
    expect(loaded.memory.smart.dataDir).toBe('~/custom-memory')
  })

  it('backs up invalid JSON and replaces it with defaults', async () => {
    const home = await mkdtemp(join(tmpdir(), 'ds-gui-settings-'))
    const settingsPath = resolveWorkbenchSettingsPath(home)
    await mkdir(join(settingsPath, '..'), { recursive: true })
    await writeFile(settingsPath, '{ invalid json', 'utf8')

    const store = new JsonSettingsStore({ home })
    const loaded = await store.load()
    const files = await readdir(join(settingsPath, '..'))
    const backupName = files.find((file) => file.startsWith('settings.invalid-'))

    expect(loaded.workspaceRoot.length).toBeGreaterThan(0)
    expect(backupName).toBeTruthy()
    expect(await readFile(join(settingsPath, '..', backupName ?? ''), 'utf8')).toBe('{ invalid json')
    const replaced = await readFile(settingsPath, 'utf8')
    expect(() => JSON.parse(replaced)).not.toThrow()
  })

  it('throws for non-recoverable read errors', async () => {
    const home = await mkdtemp(join(tmpdir(), 'ds-gui-settings-'))
    const settingsPath = resolveWorkbenchSettingsPath(home)
    await mkdir(settingsPath, { recursive: true })

    const store = new JsonSettingsStore({ home })

    await expect(store.load()).rejects.toThrow(/Failed to read settings file/)
  })
})
