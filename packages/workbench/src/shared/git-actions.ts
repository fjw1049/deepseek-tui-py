export type GitPathActionResult =
  | {
      ok: true
      repositoryRoot: string
      fileCount: number
    }
  | {
      ok: false
      reason:
        | 'no_workspace'
        | 'not_git_repo'
        | 'git_unavailable'
        | 'invalid_paths'
        | 'error'
      message: string
    }

export type GitPushResult =
  | {
      ok: true
      repositoryRoot: string
      branch: string
      upstream: string
      commitHash: string
      pushed: boolean
    }
  | {
      ok: false
      reason:
        | 'no_workspace'
        | 'not_git_repo'
        | 'git_unavailable'
        | 'detached_head'
        | 'no_remote'
        | 'behind_remote'
        | 'rejected'
        | 'error'
      message: string
    }

export type GitPullResult =
  | {
      ok: true
      repositoryRoot: string
      branch: string
      upstream: string
      updated: boolean
    }
  | {
      ok: false
      reason:
        | 'no_workspace'
        | 'not_git_repo'
        | 'git_unavailable'
        | 'detached_head'
        | 'no_upstream'
        | 'dirty_worktree'
        | 'diverged'
        | 'error'
      message: string
    }
