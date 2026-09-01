export type GitWorkingChangeStage = 'staged' | 'unstaged' | 'partial'

export type GitChangeScope = 'working-tree' | 'staged' | 'unstaged' | 'branch'

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
      scope: GitChangeScope
      /** Base ref used by the branch comparison. */
      baseRef?: string
      files: GitWorkingChangeFile[]
      /** Exact index and working-directory layers for the grouped default view. */
      stagedFiles?: GitWorkingChangeFile[]
      unstagedFiles?: GitWorkingChangeFile[]
    }
  | {
      ok: false
      reason: 'no_workspace' | 'not_git_repo' | 'git_unavailable' | 'error'
      message: string
    }
