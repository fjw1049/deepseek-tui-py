const UNPUBLISHED_WORKTREE_LABOR = '<unpublished-worktree-labor>'
const PUBLISH_FAILED = '<publish-failed>'

export type PublishAttentionState =
  | { kind: 'hidden'; conflicts: string[] }
  | { kind: 'recovery'; conflicts: string[] }
  | { kind: 'failure'; conflicts: string[] }
  | { kind: 'conflict'; conflicts: string[] }

export function publishAttentionState(
  rawConflicts: readonly string[],
  publishBlocked: boolean
): PublishAttentionState {
  const conflicts = rawConflicts.filter(
    (item) => item !== UNPUBLISHED_WORKTREE_LABOR && item !== PUBLISH_FAILED
  )
  if (rawConflicts.includes(UNPUBLISHED_WORKTREE_LABOR)) {
    return { kind: 'recovery', conflicts }
  }
  if (rawConflicts.includes(PUBLISH_FAILED)) {
    return { kind: 'failure', conflicts }
  }
  if (publishBlocked && conflicts.length > 0) {
    return { kind: 'conflict', conflicts }
  }
  return { kind: 'hidden', conflicts }
}
