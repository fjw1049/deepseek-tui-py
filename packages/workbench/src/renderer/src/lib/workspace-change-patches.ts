import type { GitWorkingChangeFile } from '@shared/git-working-changes'
import type { ChatBlock } from '../agent/types'
import {
  collectWorkspaceChangeEntries,
  workspaceChangePatchMap
} from './workspace-change-stats'

export function buildWorkspaceChangePatchMap(
  blocks: ChatBlock[],
  gitFiles: GitWorkingChangeFile[] | null | undefined
): Map<string, string> {
  return workspaceChangePatchMap(
    collectWorkspaceChangeEntries({ blocks, gitFiles: gitFiles ?? null })
  )
}

export { lookupPatchForPath, pathHasChanges, directoryHasChanges } from './workspace-change-path'
