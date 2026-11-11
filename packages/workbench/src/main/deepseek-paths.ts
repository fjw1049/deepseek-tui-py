import { join } from 'node:path'
import { resolveWorkbenchHome } from '../shared/workbench-home'

export type DeepseekPaths = {
  home: string
  configPath: string
  mcpPath: string
  hooksDir: string
  skillsDir: string
  threadsDir: string
  sessionsDir: string
  stateDbPath: string
}

/** User-level ``~/.deepseek`` (or ``$DEEPSEEK_HOME``). */
export function resolveUserDeepseekDir(): string {
  return resolveWorkbenchHome()
}

export function resolveDeepseekPaths(): DeepseekPaths {
  const home = resolveUserDeepseekDir()
  return {
    home,
    configPath: join(home, 'config.toml'),
    mcpPath: join(home, 'mcp.json'),
    hooksDir: join(home, 'hooks'),
    skillsDir: join(home, 'skills'),
    threadsDir: join(home, 'threads'),
    sessionsDir: join(home, 'sessions'),
    stateDbPath: join(home, 'state.db')
  }
}

export function resolveDeepseekConfigPath(): string {
  return resolveDeepseekPaths().configPath
}

export function resolveMcpConfigPath(): string {
  return resolveDeepseekPaths().mcpPath
}

export function resolveWorkbenchUsageLedgerPath(): string {
  return join(resolveUserDeepseekDir(), 'usage.json')
}
