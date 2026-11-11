const test = require('node:test')
const assert = require('node:assert/strict')
const { createHash } = require('node:crypto')
const { mkdtempSync, mkdirSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } = require('node:fs')
const { join, resolve } = require('node:path')
const { tmpdir } = require('node:os')
const { ensureBundledRuntime } = require('./after-pack.cjs')

test('packages only current, target-matched runtimes, including multi-architecture collections', async () => {
  const directory = mkdtempSync(join(tmpdir(), 'runtime-pack-check-'))
  const previous = process.env.DEEPSEEK_GUI_PYTHON_RUNTIME
  process.env.DEEPSEEK_GUI_PYTHON_RUNTIME = directory
  const source = join(directory, 'linux-x64')
  mkdirSync(source)
  const context = { electronPlatformName: 'linux', arch: 'x64', appOutDir: join(directory, 'app') }
  try {
    await assert.rejects(ensureBundledRuntime(context), /Build the Python runtime first/)
    writeFileSync(join(source, 'manifest.json'), '{}')
    await assert.rejects(ensureBundledRuntime(context), /Stale Python runtime/)
    const project = resolve(__dirname, '../../..')
    const sourceRoot = join(project, 'src/deepseek_tui')
    const files = []
    function walk(dir, prefix = '') {
      for (const name of readdirSync(dir)) {
        if (name === '__pycache__' || name.endsWith('.pyc')) continue
        const path = join(dir, name)
        if (statSync(path).isDirectory()) walk(path, prefix + name + '/')
        else files.push(prefix + name)
      }
    }
    walk(sourceRoot)
    const hash = createHash('sha256')
    for (const file of files.sort()) { hash.update(file + '\0'); hash.update(readFileSync(join(sourceRoot, file))) }
    const manifest = { source_sha256: hash.digest('hex'),
      lock_sha256: createHash('sha256').update(readFileSync(join(project, 'uv.lock'))).digest('hex'),
      platform: 'darwin', arch: 'arm64' }
    writeFileSync(join(source, 'manifest.json'), JSON.stringify(manifest))
    await assert.rejects(ensureBundledRuntime(context), /target mismatch/)
    manifest.platform = 'linux'; manifest.arch = 'x64'
    writeFileSync(join(source, 'manifest.json'), JSON.stringify(manifest))
    writeFileSync(join(source, 'payload.txt'), 'bundle contents')
    await ensureBundledRuntime(context)
    assert.equal(readFileSync(join(context.appOutDir, 'resources/python-runtime/payload.txt'), 'utf8'), 'bundle contents')
  } finally {
    if (previous === undefined) delete process.env.DEEPSEEK_GUI_PYTHON_RUNTIME
    else process.env.DEEPSEEK_GUI_PYTHON_RUNTIME = previous
    rmSync(directory, { recursive: true, force: true })
  }
})
