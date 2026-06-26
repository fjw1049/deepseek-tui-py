export type GitLogCommit = {
  hash: string
  shortHash: string
  parents: string[]
  subject: string
  author: string
  authoredAt: string
}

export type GitLogUpstream = {
  ref: string
  hash: string
  ahead: number
  behind: number
}

export type GitLogResult =
  | {
      ok: true
      repositoryRoot: string
      branch: string | null
      headHash: string
      upstream: GitLogUpstream | null
      commits: GitLogCommit[]
    }
  | {
      ok: false
      reason: 'no_workspace' | 'not_git_repo' | 'git_unavailable' | 'error'
      message: string
    }
