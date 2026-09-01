export type GitBranchRow = {
  name: string
  current: boolean
}

export type GitBranchesResult =
  | {
      ok: true
      repositoryRoot: string
      currentBranch: string | null
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
