import extract from 'extract-zip'
import { resolve, sep } from 'node:path'

/** Extract uploaded skills into a fresh temporary directory; never materialize links. */
export async function extractSkillArchive(zipPath: string, directory: string): Promise<void> {
  const root = resolve(directory)
  let totalBytes = 0
  let entries = 0
  await extract(zipPath, {
    dir: root,
    onEntry: (entry) => {
      totalBytes += entry.uncompressedSize
      if (++entries > 10_000 || entry.uncompressedSize > 32 * 1024 * 1024 || totalBytes > 128 * 1024 * 1024) {
        throw new Error('Skill archive exceeds extraction limits (10,000 entries, 32 MiB per file, 128 MiB total)')
      }
      const destination = resolve(root, entry.fileName)
      if (destination !== root && !destination.startsWith(root + sep)) {
        throw new Error(`Unsafe zip entry: ${entry.fileName}`)
      }
      // A link followed by another entry with the same name can overwrite its
      // external target even when the archive entry's textual path is inside root.
      if (((entry.externalFileAttributes >>> 16) & 0o170000) === 0o120000) {
        throw new Error(`Symbolic links are not supported in skill archives: ${entry.fileName}`)
      }
    }
  })
}
