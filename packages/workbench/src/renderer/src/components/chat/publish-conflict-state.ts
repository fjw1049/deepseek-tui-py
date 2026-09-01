import type { PublishIssue } from '../../agent/types'

const UNPUBLISHED_WORKTREE_LABOR = '<unpublished-worktree-labor>'
const PUBLISH_FAILED = '<publish-failed>'
const MISSING_WORKTREE = '<missing-worktree>'

export type PublishAttentionState =
  | { kind: 'hidden'; conflicts: string[] }
  | { kind: 'recovery'; conflicts: string[] }
  | { kind: 'failure'; conflicts: string[] }
  | { kind: 'missing'; conflicts: string[] }
  | { kind: 'conflict'; conflicts: string[] }

/** Bind a destructive recovery confirmation to one runtime state snapshot. */
export function publishRecoveryDecisionKey(
  attention: PublishAttentionState,
  updatedAt?: string
): string | null {
  if (attention.kind !== 'recovery') return null
  return JSON.stringify(['recovery', updatedAt ?? null, ...attention.conflicts])
}

export function publishAttentionState(
  rawConflicts: readonly string[],
  publishBlocked: boolean,
  publishIssue?: PublishIssue
): PublishAttentionState {
  let issue = publishIssue
  let conflicts = [...rawConflicts]

  // Older runtimes encoded the reason as one entry in the path array. Remove
  // only the selected reason occurrence: another marker-shaped entry may be a
  // perfectly legal filename. A structured value, including null, always wins.
  if (publishIssue === undefined) {
    const marker = rawConflicts.includes(MISSING_WORKTREE)
      ? MISSING_WORKTREE
      : rawConflicts.includes(UNPUBLISHED_WORKTREE_LABOR)
        ? UNPUBLISHED_WORKTREE_LABOR
        : rawConflicts.includes(PUBLISH_FAILED)
          ? PUBLISH_FAILED
          : null
    issue =
      marker === MISSING_WORKTREE
        ? 'missing'
        : marker === UNPUBLISHED_WORKTREE_LABOR
          ? 'recovery'
          : marker === PUBLISH_FAILED
            ? 'failure'
            : null
    if (marker) {
      const markerIndex = conflicts.indexOf(marker)
      conflicts = conflicts.filter((_, index) => index !== markerIndex)
    }
  }

  if (issue === 'missing') return { kind: 'missing', conflicts }
  if (issue === 'recovery') return { kind: 'recovery', conflicts }
  if (issue === 'failure') return { kind: 'failure', conflicts }
  if (publishBlocked && conflicts.length > 0) {
    return { kind: 'conflict', conflicts }
  }
  return { kind: 'hidden', conflicts }
}
