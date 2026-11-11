import { existsSync, mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { tmpdir } from 'node:os'
import { delimiter, join, resolve } from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { bundledPythonRuntime, resolveDefaultPythonBin, resolveRuntimeLauncher, runtimeSpawnEnv } from './resolve-python-runtime'
import { resolveUserDeepseekDir } from './deepseek-paths'

const repoRoot = resolve(import.meta.dirname, '../../../..')
const repoVenvPython =
  process.platform === 'win32'
    ? join(repoRoot, '.venv', 'Scripts', 'python.exe')
    : join(repoRoot, '.venv', 'bin', 'python')

it('selects a native bundled interpreter and rejects a different architecture', () => {
  const resources = mkdtempSync(join(tmpdir(), 'ds-bundled-runtime-'))
  const root = join(resources, 'python-runtime')
  mkdirSync(root)
  writeFileSync(join(root, 'python3'), '')
  const manifest = { platform: process.platform, arch: process.arch, python: 'python3' }
  try {
    writeFileSync(join(root, 'manifest.json'), JSON.stringify(manifest))
    expect(bundledPythonRuntime(resources)).toEqual({ bin: join(root, 'python3'), packages: join(root, 'site-packages') })
    writeFileSync(join(root, 'manifest.json'), JSON.stringify({ ...manifest, arch: 'wrong' }))
    expect(() => bundledPythonRuntime(resources)).toThrow('another platform')
    writeFileSync(join(root, 'manifest.json'), JSON.stringify({ ...manifest, python: '../python3' }))
    expect(() => bundledPythonRuntime(resources)).toThrow('invalid')
  } finally { rmSync(resources, { recursive: true, force: true }) }
})

describe('resolveRuntimeLauncher', () => {
  const envKeys = ['DEEPSEEK_PYTHON', 'DEEPSEEK_REPO_ROOT'] as const
  const savedEnv: Partial<Record<(typeof envKeys)[number], string>> = {}

  afterEach(() => {
    vi.unstubAllEnvs()
    for (const key of envKeys) {
      if (savedEnv[key] === undefined) delete process.env[key]
      else process.env[key] = savedEnv[key]
      delete savedEnv[key]
    }
  })

  it('passes an absolute home to Python launched from another directory', () => {
    const directory = mkdtempSync(join(tmpdir(), 'ds-runtime-home-'))
    vi.stubEnv('DEEPSEEK_HOME', 'relative-data-home')
    try {
      const expected = resolveUserDeepseekDir()
      const env = runtimeSpawnEnv()
      const withExisting = runtimeSpawnEnv({ ...process.env, PYTHONPATH: directory })
      expect(withExisting.PYTHONPATH).toBe(`${join(repoRoot, 'src')}${delimiter}${directory}`)
      const actual = execFileSync(repoVenvPython, ['-c',
        'from deepseek_tui.config.paths import user_deepseek_dir; print(user_deepseek_dir().absolute())'
      ], { cwd: directory, env: { ...env, PYTHONPATH: join(repoRoot, 'src') }, encoding: 'utf8' }).trim()
      expect(actual).toBe(expected)
    } finally { rmSync(directory, { recursive: true, force: true }) }
  })

  it('treats explicit Python interpreters as module launchers', () => {
    if (!existsSync(repoVenvPython)) return
    expect(resolveRuntimeLauncher(repoVenvPython)).toEqual({
      bin: repoVenvPython,
      prefixArgs: ['-m', 'deepseek_tui']
    })
  })

  it('uses explicit deepseek CLI path without -m prefix', () => {
    // Use a path that exists so we do not trigger the missing-path fallback.
    const bin = process.execPath
    expect(resolveRuntimeLauncher(bin)).toEqual({
      bin,
      prefixArgs: []
    })
  })

  it('falls back when settings binaryPath points at a missing file', () => {
    savedEnv.DEEPSEEK_PYTHON = process.env.DEEPSEEK_PYTHON
    process.env.DEEPSEEK_PYTHON = '/env/python'
    expect(resolveRuntimeLauncher('/Users/user/missing/.venv/bin/python')).toEqual({
      bin: '/env/python',
      prefixArgs: ['-m', 'deepseek_tui']
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
