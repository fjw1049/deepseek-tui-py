export type GitCommitPayload = {
  workspaceRoot: string
  message: string
  paths?: string[]
}

export type GitCommitResult =
  | {
      ok: true
      repositoryRoot: string
      commitHash: string
      summary: string
      fileCount: number
    }
  | {
      ok: false
      reason:
        | 'no_workspace'
        | 'not_git_repo'
        | 'git_unavailable'
        | 'invalid_message'
        | 'nothing_to_commit'
        | 'error'
      message: string
    }

export type GitCommitMessageSuggestionResult =
  | {
      ok: true
      message: string
    }
  | {
      ok: false
      reason:
        | 'no_workspace'
        | 'not_git_repo'
        | 'git_unavailable'
        | 'nothing_to_commit'
        | 'error'
      message: string
    }
