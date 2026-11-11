import { existsSync, readFileSync } from 'node:fs'
import { basename, delimiter, join, resolve } from 'node:path'
import { resolveDeepseekConfigPath, resolveMcpConfigPath, resolveUserDeepseekDir } from './deepseek-paths'

export type RuntimeLauncher = {
  bin: string
  prefixArgs: string[]
}

const PYTHON_MAIN_MARKER = join('src', 'deepseek_tui', '__main__.py')

export function bundledPythonRuntime(resources = process.resourcesPath): { bin: string; packages: string } | undefined {
  if (!resources) return undefined
  const root = join(resources, 'python-runtime')
  const manifestPath = join(root, 'manifest.json')
  if (!existsSync(manifestPath)) return undefined
  const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'))
  const bin = resolve(root, String(manifest.python))
  if (manifest.platform !== process.platform || manifest.arch !== process.arch || !bin.startsWith(root + (process.platform === 'win32' ? '\\' : '/')) || !existsSync(bin)) {
    throw new Error('Bundled Python runtime is invalid or built for another platform')
  }
  return { bin, packages: join(root, 'site-packages') }
}

/** Monorepo root containing ``src/deepseek_tui`` (set by dev-workbench.sh or auto-detect). */
export function resolveRepoRoot(): string | undefined {
  const fromEnv = process.env.DEEPSEEK_REPO_ROOT?.trim()
  if (fromEnv && existsSync(join(fromEnv, PYTHON_MAIN_MARKER))) {
    return resolve(fromEnv)
  }

  let dir = process.cwd()
  for (let depth = 0; depth < 8; depth += 1) {
    if (existsSync(join(dir, PYTHON_MAIN_MARKER))) {
      return dir
    }
    const parent = resolve(dir, '..')
    if (parent === dir) break
    dir = parent
  }
  return undefined
}

function repoVenvPythonBin(): string | undefined {
  const repoRoot = resolveRepoRoot()
  if (!repoRoot) return undefined
  const bin =
    process.platform === 'win32'
      ? join(repoRoot, '.venv', 'Scripts', 'python.exe')
      : join(repoRoot, '.venv', 'bin', 'python')
  return existsSync(bin) ? bin : undefined
}

export function resolveDefaultPythonBin(): string {
  const fromEnv = process.env.DEEPSEEK_PYTHON?.trim()
  if (fromEnv) return fromEnv
  return bundledPythonRuntime()?.bin ?? repoVenvPythonBin() ?? 'python3'
}

function isPythonInterpreterPath(path: string): boolean {
  const base = basename(path).toLowerCase()
  return (
    base === 'python' ||
    base === 'python3' ||
    base === 'python.exe' ||
    /^python3(\.\d+)?$/.test(base)
  )
}

/**
 * Settings → Runtime → binary path is the deepseek CLI when set.
 * If a Python interpreter was saved by mistake (e.g. repo `.venv/bin/python`),
 * still launch via `-m deepseek_tui` so `serve --http` works.
 *
 * Absolute/relative paths that no longer exist (copied settings from another
 * machine/user) fall back to auto-detect instead of failing spawn with ENOENT.
 */
export function resolveRuntimeLauncher(binaryPath: string | undefined): RuntimeLauncher {
  const explicit = binaryPath?.trim()
  if (explicit) {
    const looksLikeFilesystemPath = explicit.includes('/') || explicit.includes('\\')
    if (looksLikeFilesystemPath && !existsSync(explicit)) {
      return { bin: resolveDefaultPythonBin(), prefixArgs: ['-m', 'deepseek_tui'] }
    }
    if (isPythonInterpreterPath(explicit)) {
      return { bin: explicit, prefixArgs: ['-m', 'deepseek_tui'] }
    }
    return { bin: explicit, prefixArgs: [] }
  }
  return { bin: resolveDefaultPythonBin(), prefixArgs: ['-m', 'deepseek_tui'] }
}

export function runtimeLauncherLabel(launcher: RuntimeLauncher): string {
  return [launcher.bin, ...launcher.prefixArgs].join(' ')
}

/** Env vars for spawning the Python runtime from the monorepo checkout. */
export function runtimeSpawnEnv(base: NodeJS.ProcessEnv = process.env): NodeJS.ProcessEnv {
  const env = { ...base }
  const bundled = process.env.DEEPSEEK_PYTHON?.trim() ? undefined : bundledPythonRuntime()
  const repoRoot = bundled ? undefined : resolveRepoRoot()
  if (bundled) {
    env.PYTHONPATH = bundled.packages
    env.PYTHONNOUSERSITE = '1'
    delete env.PYTHONHOME
    delete env.DEEPSEEK_REPO_ROOT
  }
  if (repoRoot) {
    env.DEEPSEEK_REPO_ROOT = repoRoot
    const srcPath = join(repoRoot, 'src')
    env.PYTHONPATH = env.PYTHONPATH ? `${srcPath}${delimiter}${env.PYTHONPATH}` : srcPath
    // User state (config, mcp, skills, runtime.token) defaults to ~/.deepseek.
    // Repo .deepseek/config.toml is merged as a project override by ConfigLoader.
  }
  env.DEEPSEEK_CONFIG_PATH = resolveDeepseekConfigPath()
  env.DEEPSEEK_MCP_CONFIG = resolveMcpConfigPath()
  // The child may start in another cwd; pass the same absolute home used by GUI/token storage.
  env.DEEPSEEK_HOME = resolveUserDeepseekDir()
  return env
}

export function runtimeSpawnCwd(): string | undefined {
  return !process.env.DEEPSEEK_PYTHON?.trim() && bundledPythonRuntime() ? undefined : resolveRepoRoot()
}
