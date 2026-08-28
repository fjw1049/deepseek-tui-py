import { useEffect, useMemo, useState, type MouseEvent, type ReactElement, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import {
  basenameOfPath,
  classifyWorkspacePath,
  formatFileLineRange,
  parseComposerPathMentions,
  resolveWorkspaceRevealPath
} from '../../lib/file-chip'
import {
  useValidatedFileReference,
  type FileReferenceCandidate
} from '../../lib/file-reference-validation'
import { revealWorkspacePathInFolder } from '../../lib/open-workspace-path'
import { useThreadFilesystemRoot } from '../../lib/use-thread-filesystem-root'
import { previewWorkspaceFile } from '../../lib/workspace-file-preview'
import { useChatStore } from '../../store/chat-store'
import { FileKindIcon } from './FileKindIcon'

export function FileTypeIcon({
  path,
  className
}: {
  path: string
  className?: string
}): ReactElement {
  return <FileKindIcon path={path} directory={classifyWorkspacePath(path) === 'directory'} className={className} />
}

export type FileChipProps = {
  path: string
  line?: number
  column?: number
  endLine?: number
  label?: ReactNode
  variant?: 'inline' | 'list'
  className?: string
  /** Skip workspace validation (tool rows already resolved the path). */
  skipValidation?: boolean
}

export function FileChip({
  path,
  line,
  column,
  endLine,
  label,
  variant = 'inline',
  className,
  skipValidation = false
}: FileChipProps): ReactElement {
  const { t } = useTranslation('common')
  const workspaceRoot = useThreadFilesystemRoot()
  const workspaceDirtyTick = useChatStore((state) => state.workspaceDirtyTick)
  const setError = useChatStore((state) => state.setError)
  const [pickerOpen, setPickerOpen] = useState(false)
  const target = useMemo(
    () =>
      skipValidation
        ? null
        : {
            path,
            ...(line && line > 0 ? { line } : {}),
            ...(column && column > 0 ? { column } : {})
          },
    [column, line, path, skipValidation]
  )
  const { validation, retry } = useValidatedFileReference(
    target,
    workspaceRoot || undefined,
    workspaceDirtyTick
  )
  const kind =
    validation.status === 'valid' && validation.kind
      ? validation.kind
      : classifyWorkspacePath(path)
  const directory = kind === 'directory'
  const name = label ?? basenameOfPath(path)
  const lineLabel = formatFileLineRange(line, endLine)
  const location = `${path}${formatFileLineRange(line, endLine)}${line && column ? `:${column}` : ''}`
  const title =
    validation.status === 'pending'
      ? `${location} — ${t('fileReferenceResolving')}`
      : validation.status === 'invalid'
        ? `${location} — ${validation.message}`
        : validation.status === 'ambiguous'
          ? `${location} — ${t('fileReferenceMultiple')}`
          : location
  const classes = [
    'ds-file-chip',
    variant === 'list' ? 'ds-file-chip--list' : '',
    validation.status === 'pending' ? 'ds-file-chip--pending' : '',
    validation.status === 'invalid' ? 'ds-file-chip--invalid' : '',
    validation.status === 'ambiguous' ? 'ds-file-chip--ambiguous' : '',
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

  const reportRevealFailure = (result: Awaited<ReturnType<typeof revealWorkspacePathInFolder>>): void => {
    if (!result.ok) setError(`${t('fileReferenceOpenFailed')}: ${result.message}`)
  }

  const openCandidate = (candidate: FileReferenceCandidate): void => {
    setPickerOpen(false)
    if (candidate.kind === 'directory') {
      void revealWorkspacePathInFolder(candidate.path).then(reportRevealFailure)
      return
    }
    previewWorkspaceFile({
      path: candidate.path,
      ...(line && line > 0 ? { line } : {}),
      ...(column && column > 0 ? { column } : {}),
      workspaceRoot: workspaceRoot || undefined
    })
  }

  const activate = (event: MouseEvent<HTMLButtonElement>): void => {
    event.preventDefault()
    event.stopPropagation()
    if (validation.status === 'ambiguous') {
      setPickerOpen(true)
      return
    }
    if (kind === 'directory') {
      void revealWorkspacePathInFolder(
        resolveWorkspaceRevealPath(
          path,
          validation.status === 'valid' ? validation.path : undefined,
          workspaceRoot || undefined
        )
      ).then(reportRevealFailure)
      return
    }
    const openPath =
      validation.status === 'valid' && validation.kind !== 'directory' && validation.path
        ? validation.path
        : path
    previewWorkspaceFile({
      path: openPath,
      ...(line && line > 0 ? { line } : {}),
      ...(column && column > 0 ? { column } : {}),
      workspaceRoot: workspaceRoot || undefined
    })
  }

  if (!skipValidation && (validation.status === 'pending' || validation.status === 'invalid')) {
    return (
      <span
        className={classes}
        title={title}
        aria-disabled="true"
        onMouseEnter={validation.status === 'invalid' ? retry : undefined}
      >
        {inner}
      </span>
    )
  }

  return (
    <>
      <button type="button" className={classes} title={title} onClick={activate}>
        {inner}
      </button>
      {pickerOpen && validation.status === 'ambiguous' ? (
        <FileReferencePickerDialog
          sourcePath={path}
          workspaceRoot={workspaceRoot}
          candidates={validation.candidates}
          onChoose={openCandidate}
          onClose={() => setPickerOpen(false)}
        />
      ) : null}
    </>
  )
}

function candidateLabel(path: string, workspaceRoot: string): string {
  const normalizedPath = path.replace(/\\/g, '/')
  const normalizedRoot = workspaceRoot.trim().replace(/\\/g, '/').replace(/\/+$/, '')
  if (normalizedRoot && normalizedPath.startsWith(`${normalizedRoot}/`)) {
    return normalizedPath.slice(normalizedRoot.length + 1)
  }
  return normalizedPath
}

function FileReferencePickerDialog({
  sourcePath,
  workspaceRoot,
  candidates,
  onChoose,
  onClose
}: {
  sourcePath: string
  workspaceRoot: string
  candidates: FileReferenceCandidate[]
  onChoose: (candidate: FileReferenceCandidate) => void
  onClose: () => void
}): ReactElement {
  const { t } = useTranslation('common')

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  return createPortal(
    <div
      className="ds-no-drag fixed inset-0 z-[240] flex items-center justify-center bg-black/45 p-4"
      onMouseDown={(event) => {
        if (event.currentTarget === event.target) onClose()
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('fileReferenceChoose')}
        className="w-full max-w-xl overflow-hidden rounded-2xl border border-ds-border bg-ds-elevated shadow-panel"
      >
        <div className="flex items-start justify-between gap-3 border-b border-ds-border px-4 py-3">
          <div className="min-w-0">
            <h2 className="text-[14px] font-semibold text-ds-ink">{t('fileReferenceChoose')}</h2>
            <p className="mt-0.5 truncate text-[12px] text-ds-faint">{sourcePath}</p>
          </div>
          <button
            type="button"
            className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-ds-faint hover:bg-ds-hover hover:text-ds-ink"
            onClick={onClose}
            aria-label={t('close')}
          >
            ×
          </button>
        </div>
        <div className="max-h-[52vh] overflow-y-auto p-2">
          {candidates.map((candidate) => (
            <button
              key={candidate.path}
              type="button"
              className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-[13px] text-ds-ink hover:bg-ds-hover"
              title={candidate.path}
              onClick={() => onChoose(candidate)}
            >
              <FileKindIcon path={candidate.path} directory={candidate.kind === 'directory'} />
              <span className="min-w-0 break-all">{candidateLabel(candidate.path, workspaceRoot)}</span>
            </button>
          ))}
        </div>
      </div>
    </div>,
    document.body
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
