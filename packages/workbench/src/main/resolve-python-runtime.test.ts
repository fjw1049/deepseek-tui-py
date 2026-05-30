import { existsSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import { resolveDefaultPythonBin, resolveRuntimeLauncher } from './resolve-python-runtime'

const repoRoot = resolve(import.meta.dirname, '../../../..')
const repoVenvPython =
  process.platform === 'win32'
    ? join(repoRoot, '.venv', 'Scripts', 'python.exe')
    : join(repoRoot, '.venv', 'bin', 'python')

describe('resolveRuntimeLauncher', () => {
  const envKeys = ['DEEPSEEK_PYTHON', 'DEEPSEEK_REPO_ROOT'] as const
  const savedEnv: Partial<Record<(typeof envKeys)[number], string>> = {}

  afterEach(() => {
    for (const key of envKeys) {
      if (savedEnv[key] === undefined) delete process.env[key]
      else process.env[key] = savedEnv[key]
      delete savedEnv[key]
    }
  })

  it('uses explicit binaryPath from Settings', () => {
    expect(resolveRuntimeLauncher('/custom/python')).toEqual({
      bin: '/custom/python',
      prefixArgs: []
    })
  })

  it('prefers DEEPSEEK_PYTHON over repo venv', () => {
    savedEnv.DEEPSEEK_PYTHON = process.env.DEEPSEEK_PYTHON
    process.env.DEEPSEEK_PYTHON = '/env/python'
    expect(resolveRuntimeLauncher('')).toEqual({
      bin: '/env/python',
      prefixArgs: ['-m', 'deepseek_tui']
    })
  })

  it('prefers repo .venv python when present and no env override', () => {
    if (!existsSync(repoVenvPython)) return

    savedEnv.DEEPSEEK_PYTHON = process.env.DEEPSEEK_PYTHON
    delete process.env.DEEPSEEK_PYTHON
    savedEnv.DEEPSEEK_REPO_ROOT = process.env.DEEPSEEK_REPO_ROOT
    process.env.DEEPSEEK_REPO_ROOT = repoRoot

    expect(resolveDefaultPythonBin()).toBe(repoVenvPython)
    expect(resolveRuntimeLauncher(undefined).bin).toBe(repoVenvPython)
  })

  it('falls back to python3 when no venv is available', () => {
    const emptyDir = mkdtempSync(join(tmpdir(), 'ds-gui-python-'))
    const prevCwd = process.cwd()
    savedEnv.DEEPSEEK_PYTHON = process.env.DEEPSEEK_PYTHON
    delete process.env.DEEPSEEK_PYTHON
    savedEnv.DEEPSEEK_REPO_ROOT = process.env.DEEPSEEK_REPO_ROOT
    delete process.env.DEEPSEEK_REPO_ROOT
    try {
      process.chdir(emptyDir)
      expect(resolveDefaultPythonBin()).toBe('python3')
    } finally {
      process.chdir(prevCwd)
    }
  })
})
