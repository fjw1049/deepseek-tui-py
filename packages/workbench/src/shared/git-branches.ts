export type GitBranchRow = {
  name: string
  current: boolean
}

export type GitBranchesResult =
  | {
      ok: true
      repositoryRoot: string
      currentBranch: string | null
      branches: GitBranchRow[]
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
