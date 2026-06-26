#!/usr/bin/env node
/**
 * Inject monorepo Python env before electron-vite dev (mirrors ../../scripts/dev-workbench.sh).
 */
const { existsSync } = require('node:fs')
const { join, resolve } = require('node:path')
const { spawnSync } = require('node:child_process')

const workbenchRoot = resolve(__dirname, '..')
const repoRoot = resolve(workbenchRoot, '../..')
const marker = join(repoRoot, 'src', 'deepseek_tui', '__main__.py')
const venvPython =
  process.platform === 'win32'
    ? join(repoRoot, '.venv', 'Scripts', 'python.exe')
    : join(repoRoot, '.venv', 'bin', 'python')

const env = { ...process.env }

if (existsSync(marker)) {
  env.DEEPSEEK_REPO_ROOT = repoRoot
  const srcPath = join(repoRoot, 'src')
  env.PYTHONPATH = env.PYTHONPATH ? `${srcPath}:${env.PYTHONPATH}` : srcPath
}

if (!env.DEEPSEEK_PYTHON?.trim() && existsSync(venvPython)) {
  env.DEEPSEEK_PYTHON = venvPython
}

env.DEEPSEEK_SKIP_KEYRING = '1'
// Overlay rich usage mock in local dev unless explicitly disabled.
if (env.DEEPSEEK_USAGE_MOCK !== '0') {
  env.DEEPSEEK_USAGE_MOCK = '1'
}
delete env.ELECTRON_RUN_AS_NODE

const result = spawnSync(process.argv[2], process.argv.slice(3), {
  cwd: workbenchRoot,
  env,
  stdio: 'inherit',
  shell: false
})

process.exit(result.status ?? 1)
