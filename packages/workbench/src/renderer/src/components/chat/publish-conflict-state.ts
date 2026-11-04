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

/**
 * Identity of the question the user is answering: which kind of choice and
 * which files. A pending confirmation is dropped as soon as it changes. Byte
 * level staleness is rejected by the runtime through the recovery token.
 */
export function publishDecisionKey(attention: PublishAttentionState): string | null {
  if (
    attention.kind !== 'recovery' &&
    attention.kind !== 'conflict' &&
    attention.kind !== 'missing'
  ) {
    return null
  }
  return JSON.stringify([attention.kind, ...attention.conflicts])
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
