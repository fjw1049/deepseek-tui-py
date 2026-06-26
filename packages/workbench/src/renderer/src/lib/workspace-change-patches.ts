import type { GitWorkingChangeFile } from '@shared/git-working-changes'
import type { ChatBlock } from '../agent/types'
import { extractDiffFilePath, looksLikeUnifiedDiff } from './diff-stats'
import { normalizeChangePath } from './workspace-change-path'

export function buildWorkspaceChangePatchMap(
  blocks: ChatBlock[],
  gitFiles: GitWorkingChangeFile[] | null | undefined
): Map<string, string> {
  const map = new Map<string, string>()

  for (const block of blocks) {
    if (!(block.kind === 'tool' && block.toolKind === 'file_change')) continue
    const detail = block.detail?.trim() ?? ''
    if (!looksLikeUnifiedDiff(detail)) continue
    const path = extractDiffFilePath(detail, block.filePath)
    const key = normalizeChangePath(path)
    if (!key) continue
    map.set(key, detail)
  }

  for (const file of gitFiles ?? []) {
    const key = normalizeChangePath(file.path)
    if (!key || map.has(key)) continue
    const patch = file.patch.trim()
    if (patch) map.set(key, patch)
  }

  return map
}

export { lookupPatchForPath, pathHasChanges, directoryHasChanges } from './workspace-change-path'
