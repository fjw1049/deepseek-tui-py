const { createHash } = require('node:crypto')
const { execFileSync } = require('node:child_process')
const { existsSync, readFileSync, readdirSync, statSync, copyFileSync, unlinkSync } = require('node:fs')
const { chmod, cp, mkdir } = require('node:fs/promises')
const { join, resolve } = require('node:path')
const { buildWindowMaterialAddon } = require('./build-window-material.cjs')

function targetArch(context) {
  return typeof context.arch === 'string' ? context.arch : ['ia32', 'x64', 'armv7l', 'arm64', 'universal'][context.arch]
}

function sourceHash() {
  const root = resolve(__dirname, '../../../src/deepseek_tui')
  const files = []
  function visit(dir, prefix = '') {
    for (const name of readdirSync(dir)) {
      if (name === '__pycache__' || name.endsWith('.pyc')) continue
      const path = join(dir, name), relative = prefix + name
      if (statSync(path).isDirectory()) visit(path, relative + '/')
      else files.push(relative)
    }
  }
  visit(root)
  const hash = createHash('sha256')
  for (const file of files.sort()) { hash.update(file + '\0'); hash.update(readFileSync(join(root, file))) }
  return hash.digest('hex')
}

async function ensureBundledRuntime(context) {
  const platform = context.electronPlatformName === 'win' ? 'win32' : context.electronPlatformName
  const root = resolve(process.env.DEEPSEEK_GUI_PYTHON_RUNTIME || join(__dirname, '..', '.cache', 'python-runtime'))
  // Multi-target releases may collect separately built native runtimes under this root.
  const source = existsSync(join(root, 'manifest.json')) ? root : join(root, `${platform}-${targetArch(context)}`)
  const manifestPath = join(source, 'manifest.json')
  if (!existsSync(manifestPath)) {
    throw new Error('Build the Python runtime first: npm run prepare:runtime (or set DEEPSEEK_GUI_PYTHON_RUNTIME)')
  }
  const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'))
  if (manifest.source_sha256 !== sourceHash() || manifest.lock_sha256 !== createHash('sha256').update(readFileSync(resolve(__dirname, '../../../uv.lock'))).digest('hex')) {
    throw new Error('Stale Python runtime: rebuild it from the current source and uv.lock')
  }
  if (manifest.platform !== platform || manifest.arch !== targetArch(context)) {
    throw new Error(`Python runtime target mismatch: build a native ${platform}/${targetArch(context)} runtime`)
  }
  const resources = platform === 'darwin'
    ? join(context.appOutDir, `${context.packager.appInfo.productFilename}.app`, 'Contents', 'Resources')
    : join(context.appOutDir, 'resources')
  await mkdir(resources, { recursive: true })
  await cp(source, join(resources, 'python-runtime'), { recursive: true })
  await chmod(join(resources, 'python-runtime'), 0o755)
}
exports.ensureBundledRuntime = ensureBundledRuntime
exports.default = async function afterPack(context) {
  if (context.electronPlatformName === 'darwin') {
    const app = join(context.appOutDir, `${context.packager.appInfo.productFilename}.app`)
    const addon = buildWindowMaterialAddon({ arch: targetArch(context), outputPath: join(app, 'Contents', 'Frameworks', 'deepseek-window-material.node') })
    unlinkSync(`${addon}.build.json`)
    copyFileSync(join(__dirname, '../native/window-material/LICENSE'), join(app, 'Contents', 'Resources', 'window-material-LICENSE.txt'))
  }
  await ensureBundledRuntime(context)
  if (context.electronPlatformName === 'darwin' && !process.env.CSC_LINK && !process.env.CSC_NAME && !process.env.CSC_KEY_PASSWORD && process.env.MAC_SIGN !== '1') {
    execFileSync('codesign', ['--force', '--deep', '--sign', '-', '--timestamp=none', join(context.appOutDir, `${context.packager.appInfo.productFilename}.app`)], { stdio: 'inherit' })
  }
}
