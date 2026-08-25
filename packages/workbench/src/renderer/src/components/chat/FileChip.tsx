import type { MouseEvent, ReactElement, ReactNode } from 'react'
import {
  basenameOfPath,
  formatFileLineRange,
  looksLikeDirectoryPath,
  parseComposerPathMentions
} from '../../lib/file-chip'
import { useValidatedFileReference } from '../../lib/file-reference-validation'
import { revealWorkspacePathInFolder } from '../../lib/open-workspace-path'
import { useThreadFilesystemRoot } from '../../lib/use-thread-filesystem-root'
import { previewWorkspaceFile } from '../../lib/workspace-file-preview'
import { FileKindIcon } from './FileKindIcon'

export function FileTypeIcon({
  path,
  className
}: {
  path: string
  className?: string
}): ReactElement {
  return <FileKindIcon path={path} directory={looksLikeDirectoryPath(path)} className={className} />
}

export type FileChipProps = {
  path: string
  line?: number
  endLine?: number
  label?: string
  variant?: 'inline' | 'list'
  className?: string
  /** Skip workspace validation (tool rows already resolved the path). */
  skipValidation?: boolean
}

export function FileChip({
  path,
  line,
  endLine,
  label,
  variant = 'inline',
  className,
  skipValidation = false
}: FileChipProps): ReactElement {
  const workspaceRoot = useThreadFilesystemRoot()
  const target = { path, ...(line && line > 0 ? { line } : {}) }
  const validation = useValidatedFileReference(skipValidation ? null : target, workspaceRoot || undefined)
  const resolvedPath = validation.status === 'valid' ? validation.path : path
  const directory = looksLikeDirectoryPath(path)
  const name = label ?? basenameOfPath(path)
  const lineLabel = formatFileLineRange(line, endLine)
  const title = `${path}${formatFileLineRange(line, endLine)}`
  const classes = [
    'ds-file-chip',
    variant === 'list' ? 'ds-file-chip--list' : '',
    className
  ]
    .filter(Boolean)
    .join(' ')

  const inner = (
    <>
      <FileKindIcon path={path} directory={directory} />
      <span className="ds-file-chip__name">{name}</span>
      {lineLabel ? <span className="ds-file-chip__line">{lineLabel}</span> : null}
    </>
  )

  const activate = (event: MouseEvent<HTMLButtonElement>): void => {
    event.preventDefault()
    event.stopPropagation()
    if (directory) {
      void revealWorkspacePathInFolder(path)
      return
    }
    const resolved = { path: resolvedPath, ...(line && line > 0 ? { line } : {}) }
    previewWorkspaceFile({
      ...resolved,
      workspaceRoot: workspaceRoot || undefined
    })
  }

  return (
    <button type="button" className={classes} title={title} onClick={activate}>
      {inner}
    </button>
  )
}

export function UserMessageRichText({ text }: { text: string }): ReactNode {
  const mentions = parseComposerPathMentions(text)
  if (mentions.length === 0) return text

  const parts: ReactNode[] = []
  let cursor = 0
  mentions.forEach((mention, index) => {
    if (mention.start > cursor) {
      parts.push(text.slice(cursor, mention.start))
    }
    parts.push(
      <FileChip
        key={`${mention.path}:${mention.start}:${index}`}
        path={mention.path}
        line={mention.line}
        endLine={mention.endLine}
      />
    )
    cursor = mention.end
  })
  if (cursor < text.length) parts.push(text.slice(cursor))
  return parts
}
