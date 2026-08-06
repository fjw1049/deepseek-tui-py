// GUI product state is flat under ``~/.deepseek/`` (à la ``.claude`` / ``.codex``):
// settings.json + usage.json at the top level, active ``claw/`` sandbox at the top
// level, and wipeable caches under ``caches/`` (logs, pet-cache, marketplace-cache).
// Electron ``userData`` remains for Chromium caches only (plus one-shot migrations).

import { homedir } from 'node:os'
import { join, resolve } from 'node:path'

/**
 * Resolve the user-level ``~/.deepseek`` root (same root as Python ``user_deepseek_dir``).
 *
 * - ``home`` override (tests): ``{home}/.deepseek``
 * - else ``$DEEPSEEK_HOME`` when set
 * - else ``~/.deepseek``
 */
export function resolveWorkbenchHome(home?: string): string {
  if (home !== undefined) {
    return join(home, '.deepseek')
  }
  const fromEnv = process.env.DEEPSEEK_HOME?.trim()
  if (fromEnv) {
    return resolve(fromEnv)
  }
  return join(homedir(), '.deepseek')
}

/** GUI settings (theme, port, models UI, …) — flat at the top level. */
export function resolveWorkbenchSettingsPath(home?: string): string {
  return join(resolveWorkbenchHome(home), 'settings.json')
}

/** Claw / IM channel sandbox workspaces — active data at the top level, not a cache. */
export function resolveClawChannelsRoot(home?: string): string {
  return join(resolveWorkbenchHome(home), 'claw')
}

/** GUI error logs (``deepseek-gui-YYYY-MM-DD.log``) — under wipeable ``caches/``. */
export function resolveWorkbenchLogsDir(home?: string): string {
  return join(resolveWorkbenchHome(home), 'caches', 'logs')
}

/** Desktop pet spritesheet / manifest cache — under wipeable ``caches/``. */
export function resolveWorkbenchPetCacheDir(home?: string): string {
  return join(resolveWorkbenchHome(home), 'caches', 'pet-cache')
}

/** ModelScope marketplace catalog cache — under wipeable ``caches/``. */
export function resolveWorkbenchMarketplaceCacheDir(home?: string): string {
  return join(resolveWorkbenchHome(home), 'caches', 'marketplace-cache')
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
