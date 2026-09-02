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

export type GitSyncResult =
  | {
      ok: true
      repositoryRoot: string
      branch: string
      upstream: string
      action: 'up_to_date' | 'published' | 'pulled' | 'pushed' | 'merged'
      commitHash: string
      updated: boolean
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
        | 'no_upstream'
        | 'operation_in_progress'
        | 'busy'
        | 'dirty_worktree'
        | 'conflict'
        | 'recovery_required'
        | 'rejected'
        | 'error'
      message: string
      conflictedFiles?: string[]
      recovered?: boolean
    }
