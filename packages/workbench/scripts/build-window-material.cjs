// Node-API uses Electron's stable C ABI; no downloaded headers or node-gyp are needed.
const { createHash } = require('node:crypto')
const { execFileSync, spawnSync } = require('node:child_process')
const { copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, renameSync, rmSync, writeFileSync } = require('node:fs')
const { tmpdir } = require('node:os')
const { dirname, join, resolve } = require('node:path')

function buildWindowMaterialAddon({
  arch = process.arch,
  outputPath = join(__dirname, '../out/native/deepseek-window-material.node')
} = {}) {
  if (process.platform !== 'darwin') throw new Error('The window material addon requires a macOS build host')
  const targetArch = { arm64: 'arm64', x64: 'x86_64' }[arch]
  if (!targetArch) throw new Error(`Unsupported window material architecture: ${arch}`)
  const source = join(__dirname, '../native/window-material/WindowMaterial.m')
  const args = ['clang', '-x', 'objective-c', '-fobjc-arc', '-O2', '-Wall', '-Wextra', '-Werror',
    '-arch', targetArch, '-mmacosx-version-min=12.3', '-bundle', '-undefined', 'dynamic_lookup',
    '-framework', 'AppKit', source]
  const fingerprint = createHash('sha256').update(readFileSync(source)).update(readFileSync(__filename))
    .update(JSON.stringify(args)).digest('hex')
  const output = resolve(outputPath)
  const metadata = `${output}.build.json`
  if (existsSync(output) && existsSync(metadata)) {
    try {
      if (JSON.parse(readFileSync(metadata, 'utf8')).fingerprint === fingerprint &&
        spawnSync('codesign', ['--verify', '--strict', output]).status === 0) return output
    } catch { /* Rebuild an incomplete cache. */ }
  }
  const scratch = mkdtempSync(join(tmpdir(), 'deepseek-window-material-'))
  try {
    const built = join(scratch, 'deepseek-window-material.node')
    execFileSync('xcrun', [...args, '-o', built], {
      env: { ...process.env, CLANG_MODULE_CACHE_PATH: join(scratch, 'module-cache') },
      stdio: 'pipe'
    })
    execFileSync('codesign', ['--force', '--sign', '-', '--timestamp=none', built], { stdio: 'pipe' })
    mkdirSync(dirname(output), { recursive: true })
    const pending = `${output}.${process.pid}.tmp`
    copyFileSync(built, pending)
    renameSync(pending, output)
    writeFileSync(metadata, JSON.stringify({ fingerprint }))
    return output
  } finally {
    rmSync(scratch, { recursive: true, force: true })
  }
}

exports.buildWindowMaterialAddon = buildWindowMaterialAddon
if (require.main === module && process.platform === 'darwin') buildWindowMaterialAddon()
