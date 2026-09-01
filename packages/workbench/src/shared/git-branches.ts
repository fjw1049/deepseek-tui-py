export type GitBranchRow = {
  name: string
  current: boolean
}

export type GitBranchesResult =
  | {
      ok: true
      repositoryRoot: string
      /** Real attached branch. Null means HEAD is detached. */
      currentBranch: string | null
      detached: boolean
      /** Display-only nearest branch for a detached managed task checkout. */
      inferredBranch: string | null
      /** Local branches ordered by most recent commit first. */
      branches: GitBranchRow[]
      /** Repository default branch ref, preferring its remote-tracking ref. */
      defaultBranch: string | null
      /** Closest recently active ancestor branch, otherwise the default branch. */
      recommendedBase: string | null
      dirtyCount: number
      upstream: string | null
      ahead: number
      behind: number
      hasRemote: boolean
      /** Fetch failure from an explicit refresh; local branch state remains usable. */
      remoteRefreshError: string | null
    }
  | {
      ok: false
      reason:
        | 'no_workspace'
        | 'not_git_repo'
        | 'git_unavailable'
        | 'dirty_worktree'
        | 'stash_pop_conflict'
        | 'error'
      message: string
    }
