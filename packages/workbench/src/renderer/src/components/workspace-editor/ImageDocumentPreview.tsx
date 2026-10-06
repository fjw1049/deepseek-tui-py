import type { ReactElement } from 'react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useWorkspaceEditorStore } from '../../store/workspace-editor-store'
import { EditorListSkeleton } from './EditorListSkeleton'

type Props = {
  path: string
  workspaceRoot: string
}

/** Read-only image preview for workspace editor tabs. */
export function ImageDocumentPreview({ path, workspaceRoot }: Props): ReactElement {
  const { t } = useTranslation('common')
  const revision = useWorkspaceEditorStore((state) => state.previewVersion)
  const [url, setUrl] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setUrl(null)
    setError(null)

    const api = window.dsGui?.getWorkspaceHtmlPreviewUrl
    if (typeof api !== 'function') {
      setLoading(false)
      setError(t('workspacePreviewUnavailable'))
      return
    }

    void api({ path, workspaceRoot: workspaceRoot || undefined })
      .then((result) => {
        if (cancelled) return
        if (!result.ok) {
          setError(result.message)
          return
        }
        const nextUrl = new URL(result.url)
        nextUrl.searchParams.set('_ds_revision', String(revision))
        if (attempt > 0) nextUrl.searchParams.set('_ds_attempt', String(attempt))
        setUrl(nextUrl.toString())
      })
      .catch((err: unknown) => {
        if (cancelled) return
        setError(err instanceof Error ? err.message : String(err))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [path, workspaceRoot, revision, attempt, t])

  if (loading) {
    return (
      <div className="flex min-h-0 flex-1 flex-col bg-ds-sidebar">
        <EditorListSkeleton rows={5} />
      </div>
    )
  }

  if (error || !url) {
    return (
      <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-3 overflow-auto px-6 py-4 text-center text-[13px] text-ds-muted">
        <p role="alert" className="max-w-full [overflow-wrap:anywhere]">{error ?? t('workspaceEditorPickFile')}</p>
        <button type="button" className="shrink-0 rounded-lg border border-ds-border px-3 py-1.5 hover:bg-ds-hover" onClick={() => setAttempt((value) => value + 1)}>
          {t('workspacePreviewRetry')}
        </button>
      </div>
    )
  }

  return (
    <div className="flex min-h-0 flex-1 items-center justify-center overflow-auto bg-ds-sidebar p-4">
      <img
        src={url}
        alt={path.split(/[/\\]/).pop() ?? path}
        className="max-h-full max-w-full object-contain"
        draggable={false}
        onError={() => setError(t('workspaceImagePreviewFailed'))}
      />
    </div>
  )
}
