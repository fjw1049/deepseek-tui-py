import { homedir } from 'node:os'
import { join, resolve } from 'node:path'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { resolveUserDeepseekDir } from '../main/deepseek-paths'
import {
  resolveWorkbenchHome,
  resolveWorkbenchLogsDir,
  resolveWorkbenchMarketplaceCacheDir,
  resolveWorkbenchPetCacheDir
} from './workbench-home'

describe('workbench-home', () => {
  const prev = process.env.DEEPSEEK_HOME

  afterEach(() => {
    vi.unstubAllEnvs()
    if (prev === undefined) delete process.env.DEEPSEEK_HOME
    else process.env.DEEPSEEK_HOME = prev
  })

  it('defaults to ~/.deepseek (flat)', () => {
    delete process.env.DEEPSEEK_HOME
    expect(resolveWorkbenchHome()).toBe(join(homedir(), '.deepseek'))
    expect(resolveWorkbenchLogsDir()).toBe(join(homedir(), '.deepseek', 'caches', 'logs'))
  })

  it('honors DEEPSEEK_HOME like Python user_deepseek_dir', () => {
    process.env.DEEPSEEK_HOME = '/tmp/custom-deepseek-home'
    expect(resolveWorkbenchHome()).toBe('/tmp/custom-deepseek-home')
    expect(resolveWorkbenchPetCacheDir()).toBe('/tmp/custom-deepseek-home/caches/pet-cache')
    expect(resolveWorkbenchMarketplaceCacheDir()).toBe(
      '/tmp/custom-deepseek-home/caches/marketplace-cache'
    )
  })

  it('home override wins over DEEPSEEK_HOME (tests)', () => {
    process.env.DEEPSEEK_HOME = '/tmp/custom-deepseek-home'
    expect(resolveWorkbenchHome('/tmp/os-home')).toBe(join('/tmp/os-home', '.deepseek'))
  })

  it.each(['~/state', '$AUDIT_HOME/state', '${AUDIT_HOME}/state', '  state  '])(
    'shares real files with Python for DEEPSEEK_HOME=%s', (input) => {
      const directory = mkdtempSync(join(tmpdir(), 'ds-home-parity-'))
      const repo = resolve(import.meta.dirname, '../../../..')
      const python = process.platform === 'win32'
        ? join(repo, '.venv/Scripts/python.exe') : join(repo, '.venv/bin/python')
      vi.stubEnv('HOME', directory)
      vi.stubEnv('USERPROFILE', directory)
      vi.stubEnv('AUDIT_HOME', directory)
      // Keep whitespace-path testing inside the temporary directory as well.
      const raw = input.startsWith(' ') ? join(directory, input) : input
      vi.stubEnv('DEEPSEEK_HOME', raw)
      try {
        const expected = execFileSync(python, ['-c',
          'from deepseek_tui.config.paths import user_deepseek_dir; print(user_deepseek_dir().absolute())'
        ], { env: { ...process.env, PYTHONPATH: join(repo, 'src') }, encoding: 'utf8' }).replace(/\r?\n$/, '')
        expect(resolveWorkbenchHome()).toBe(expected)
        expect(resolveUserDeepseekDir()).toBe(expected)
        mkdirSync(expected, { recursive: true })
        writeFileSync(join(resolveWorkbenchHome(), 'shared.txt'), 'written by GUI')
        execFileSync(python, ['-c',
          'from deepseek_tui.config.paths import user_deepseek_dir; p=user_deepseek_dir()/"shared.txt"; assert p.read_text()=="written by GUI"; p.write_text("read by Python")'
        ], { env: { ...process.env, PYTHONPATH: join(repo, 'src') } })
        expect(readFileSync(join(resolveWorkbenchHome(), 'shared.txt'), 'utf8')).toBe('read by Python')
      } finally { rmSync(directory, { recursive: true, force: true }) }
    }
  )
})
