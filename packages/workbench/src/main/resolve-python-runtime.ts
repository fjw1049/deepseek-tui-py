import { existsSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { resolveDeepseekConfigPath, resolveMcpConfigPath } from './deepseek-paths'

export type RuntimeLauncher = {
  bin: string
  prefixArgs: string[]
}

const PYTHON_MAIN_MARKER = join('src', 'deepseek_tui', '__main__.py')

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
  return repoVenvPythonBin() ?? 'python3'
}

export function resolveRuntimeLauncher(binaryPath: string | undefined): RuntimeLauncher {
  const explicit = binaryPath?.trim()
  if (explicit) {
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
  const repoRoot = resolveRepoRoot()
  if (repoRoot) {
    env.DEEPSEEK_REPO_ROOT = repoRoot
    const srcPath = join(repoRoot, 'src')
    env.PYTHONPATH = env.PYTHONPATH ? `${srcPath}:${env.PYTHONPATH}` : srcPath
    // User state (config, mcp, skills, runtime.token) defaults to ~/.deepseek.
    // Repo .deepseek/config.toml is merged as a project override by ConfigLoader.
  }
  env.DEEPSEEK_CONFIG_PATH = resolveDeepseekConfigPath()
  env.DEEPSEEK_MCP_CONFIG = resolveMcpConfigPath()
  // Workbench-managed runtime: config.toml + DEEPSEEK_API_KEY only; skip macOS Keychain.
  env.DEEPSEEK_SKIP_KEYRING = '1'
  return env
}

export function runtimeSpawnCwd(): string | undefined {
  return resolveRepoRoot()
}
