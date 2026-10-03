import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, expect, it, vi } from 'vitest'
const handlers = vi.hoisted(() => new Map<string, (...args: any[]) => any>())
vi.mock('electron', () => ({
  ipcMain: { handle: (name: string, handler: (...args: any[]) => any) => handlers.set(name, handler) },
  dialog: {}, shell: {}, app: { getPath: () => '/tmp' }, safeStorage: {}
}))
import { registerAppIpcHandlers } from './register-app-ipc-handlers'
let root = ''
afterEach(async () => { if (root) await rm(root, { recursive: true, force: true }); handlers.clear() })
it('rejects an outdated settings snapshot and serializes competing writes', async () => {
  root = await mkdtemp(join(tmpdir(), 'ds-config-write-'))
  const path = join(root, 'config.toml')
  // Only the config handler is invoked; other registered handlers do not execute.
  registerAppIpcHandlers({ resolveDeepseekConfigPath: () => path } as Parameters<typeof registerAppIpcHandlers>[0])
  const write = handlers.get('deepseek:config:write')!
  await writeFile(path, 'latest = true\n')
  await expect(write(null, 'mail = true\n', 'old = true\n')).rejects.toThrow('Configuration changed')
  expect(await readFile(path, 'utf8')).toBe('latest = true\n')
  const results = await Promise.allSettled([
    write(null, 'first = true\n', 'latest = true\n'),
    write(null, 'second = true\n', 'latest = true\n')
  ])
  expect(results.map(result => result.status)).toEqual(['fulfilled', 'rejected'])
  expect(await readFile(path, 'utf8')).toBe('first = true\n')
})
