// Canonical GUI product state under ``~/.deepseek/workbench/``:
// settings, claw, usage, logs, pet-cache, marketplace-cache.
// Electron ``userData`` remains for Chromium caches only (plus one-shot migrations).

import { homedir } from 'node:os'
import { join, resolve } from 'node:path'

const WORKBENCH_HOME_SEGMENTS = ['.deepseek', 'workbench'] as const

/**
 * Resolve ``…/workbench``.
 *
 * - ``home`` override (tests): ``{home}/.deepseek/workbench``
 * - else ``$DEEPSEEK_HOME/workbench`` when set (same root as Python ``user_deepseek_dir``)
 * - else ``~/.deepseek/workbench``
 */
export function resolveWorkbenchHome(home?: string): string {
  if (home !== undefined) {
    return join(home, ...WORKBENCH_HOME_SEGMENTS)
  }
  const fromEnv = process.env.DEEPSEEK_HOME?.trim()
  if (fromEnv) {
    return join(resolve(fromEnv), 'workbench')
  }
  return join(homedir(), ...WORKBENCH_HOME_SEGMENTS)
}

/** GUI settings (theme, port, models UI, …). */
export function resolveWorkbenchSettingsPath(home?: string): string {
  return join(resolveWorkbenchHome(home), 'settings.json')
}

/** Claw / IM channel sandbox workspaces. */
export function resolveClawChannelsRoot(home?: string): string {
  return join(resolveWorkbenchHome(home), 'claw')
}

/** GUI error logs (``deepseek-gui-YYYY-MM-DD.log``). */
export function resolveWorkbenchLogsDir(home?: string): string {
  return join(resolveWorkbenchHome(home), 'logs')
}

/** Desktop pet spritesheet / manifest cache. */
export function resolveWorkbenchPetCacheDir(home?: string): string {
  return join(resolveWorkbenchHome(home), 'pet-cache')
}

/** ModelScope marketplace catalog cache. */
export function resolveWorkbenchMarketplaceCacheDir(home?: string): string {
  return join(resolveWorkbenchHome(home), 'marketplace-cache')
}

/** Legacy GUI home (pre-consolidation). Always under OS home, not DEEPSEEK_HOME. */
export function resolveLegacyDeepseekGuiHome(home = homedir()): string {
  return join(home, '.deepseekgui')
}

export function resolveLegacyClawChannelsRoot(home = homedir()): string {
  return join(resolveLegacyDeepseekGuiHome(home), 'claw')
}

export function resolveLegacyGuiSettingsPath(userDataPath: string): string {
  return join(userDataPath, 'deepseek-gui-settings.json')
}
