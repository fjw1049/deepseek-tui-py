import { existsSync } from 'node:fs'
import { mkdir, readdir, rename, rm } from 'node:fs/promises'
import { join } from 'node:path'

/**
 * Best-effort one-shot move of files from a legacy directory into ``dest``.
 * Skips names that already exist at the destination. Removes ``src`` when empty.
 */
export async function migrateLegacyDirContents(
  src: string,
  dest: string,
  options?: { only?: (name: string) => boolean }
): Promise<void> {
  if (!src || !dest || src === dest || !existsSync(src)) return
  await mkdir(dest, { recursive: true })
  let entries: string[]
  try {
    entries = await readdir(src)
  } catch {
    return
  }
  for (const name of entries) {
    if (options?.only && !options.only(name)) continue
    const from = join(src, name)
    const to = join(dest, name)
    if (existsSync(to)) continue
    try {
      await rename(from, to)
    } catch {
      /* cross-device rename can fail; leave legacy copy */
    }
  }
  try {
    const remaining = await readdir(src)
    if (remaining.length === 0) await rm(src, { recursive: true, force: true })
  } catch {
    /* ignore */
  }
}
