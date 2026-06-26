export type WorkspaceFileTarget = {
  path: string
  workspaceRoot?: string
  line?: number
  column?: number
}

export type WorkspaceFileReadResult =
  | {
      ok: true
      path: string
      content: string
      size: number
      truncated: boolean
      line?: number
      column?: number
    }
  | { ok: false; message: string }

export type WorkspaceFileResolveResult =
  | {
      ok: true
      path: string
    }
  | { ok: false; message: string }

export type WorkspaceTreeEntry = {
  name: string
  path: string
  kind: 'file' | 'directory'
}

export type WorkspaceListDirectoryResult =
  | {
      ok: true
      path: string
      entries: WorkspaceTreeEntry[]
    }
  | { ok: false; message: string }

export type WorkspaceFileWriteTarget = {
  path: string
  workspaceRoot?: string
  content: string
}

export type WorkspaceFileWriteResult =
  | {
      ok: true
      path: string
    }
  | { ok: false; message: string }
