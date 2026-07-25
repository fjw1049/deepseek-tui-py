import { app } from 'electron'
import { homedir } from 'node:os'
import { join } from 'node:path'
import { readdir, rm } from 'node:fs/promises'
import { stopDeepseekChildAndWait } from '../deepseek-process'

/** GUI-only home used by Claw IM workspaces — not the shared ``~/.deepseek``. */
export function resolveDeepseekGuiHome(): string {
  return join(homedir(), '.deepseekgui')
}

/**
 * Permanently remove DeepSeek GUI local data and quit.
 *
 * Deletes Electron ``userData`` contents and ``~/.deepseekgui``.
 * Does **not** delete the shared CLI directory ``~/.deepseek``.
 */
export async function deleteGuiDataAndExit(): Promise<{ ok: true } | { ok: false; message: string }> {
  try {
    await stopDeepseekChildAndWait(5_000)
  } catch {
    // Best-effort — continue wiping even if the child is already gone.
  }

  const errors: string[] = []
  const guiHome = resolveDeepseekGuiHome()
  try {
    await rm(guiHome, { recursive: true, force: true })
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
