import { homedir } from 'node:os'
import { join, resolve } from 'node:path'

export type DeepseekPaths = {
  home: string
  configPath: string
  mcpPath: string
  hooksDir: string
  skillsDir: string
}

/** User-level ``~/.deepseek`` (or ``$DEEPSEEK_HOME``). */
export function resolveUserDeepseekDir(): string {
  const fromEnv = process.env.DEEPSEEK_HOME?.trim()
  if (fromEnv) {
    return resolve(fromEnv)
  }
  return join(homedir(), '.deepseek')
}

export function resolveDeepseekPaths(): DeepseekPaths {
  const home = resolveUserDeepseekDir()
  return {
    home,
    configPath: join(home, 'config.toml'),
    mcpPath: join(home, 'mcp.json'),
    hooksDir: join(home, 'hooks'),
    skillsDir: join(home, 'skills')
  }
}

export function resolveDeepseekConfigPath(): string {
  return resolveDeepseekPaths().configPath
}

export function resolveMcpConfigPath(): string {
  return resolveDeepseekPaths().mcpPath
}

export function resolveWorkbenchUsageLedgerPath(): string {
  return join(resolveUserDeepseekDir(), 'workbench', 'usage', 'ledger-v1.json')
}
