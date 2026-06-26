export type GitWorkingChangeStage = 'staged' | 'unstaged' | 'partial'

export type GitWorkingChangeStatus =
  | 'modified'
  | 'added'
  | 'deleted'
  | 'renamed'
  | 'copied'
  | 'untracked'

export type GitWorkingChangeFile = {
  path: string
  status: GitWorkingChangeStatus
  stage: GitWorkingChangeStage
  patch: string
}

export type GitWorkingChangesResult =
  | {
      ok: true
      repositoryRoot: string
      files: GitWorkingChangeFile[]
    }
  | {
      ok: false
      reason: 'no_workspace' | 'not_git_repo' | 'git_unavailable' | 'error'
      message: string
    }
