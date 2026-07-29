import { app } from 'electron'
import { readdir, rm } from 'node:fs/promises'
import { join } from 'node:path'
import {
  resolveLegacyDeepseekGuiHome,
  resolveWorkbenchHome
} from '../../shared/workbench-home'
import { stopDeepseekChildAndWait } from '../deepseek-process'

/**
 * Permanently remove DeepSeek GUI local shell data and quit.
 *
 * Deletes:
 * - ``~/.deepseek/workbench/`` GUI product state (settings, claw, logs, caches)
 * - legacy ``~/.deepseekgui``
 * - Electron ``userData`` Chromium caches
 *
 * Does **not** delete shared runtime data under ``~/.deepseek``
 * (threads, tasks, skills, config.toml, usage ledger, …).
 */
export async function deleteGuiDataAndExit(): Promise<{ ok: true } | { ok: false; message: string }> {
  try {
    await stopDeepseekChildAndWait(5_000)
  } catch {
    // Best-effort — continue wiping even if the child is already gone.
  }

  const errors: string[] = []

  const workbenchHome = resolveWorkbenchHome()
  for (const rel of [
    'settings.json',
    'claw',
    'logs',
    'pet-cache',
    'marketplace-cache'
  ] as const) {
    try {
      await rm(join(workbenchHome, rel), { recursive: true, force: true })
    } catch (error) {
      errors.push(error instanceof Error ? error.message : String(error))
    }
  }

  const legacyGuiHome = resolveLegacyDeepseekGuiHome()
  try {
    await rm(legacyGuiHome, { recursive: true, force: true })
  } catch (error) {
    errors.push(error instanceof Error ? error.message : String(error))
  }

  const userData = app.getPath('userData')
  try {
    const entries = await readdir(userData)
    await Promise.all(
      entries.map((name) => rm(join(userData, name), { recursive: true, force: true }))
    )
  } catch (error) {
    errors.push(error instanceof Error ? error.message : String(error))
  }

  // Quit after a tick so the IPC reply can flush.
  setTimeout(() => {
    app.exit(errors.length ? 1 : 0)
  }, 120)

  if (errors.length) {
    return { ok: false, message: errors.join('; ') }
  }
  return { ok: true }
}
