import type { ReactElement } from 'react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { EditorListSkeleton } from './EditorListSkeleton'

type Props = {
  path: string
  workspaceRoot: string
}

/** Live HTML preview inside an IDE/editor pane — does not leave IDE mode. */
export function HtmlDocumentPreview({ path, workspaceRoot }: Props): ReactElement {
  const { t } = useTranslation('common')
  const [url, setUrl] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setUrl(null)
    setError(null)

    const api = window.dsGui?.getWorkspaceHtmlPreviewUrl
    if (typeof api !== 'function') {
      setLoading(false)
      setError('Preview bridge is unavailable.')
      return
    }

    void api({ path, workspaceRoot: workspaceRoot || undefined })
      .then((result) => {
        if (cancelled) return
        if (!result.ok) {
          setError(result.message)
          return
        }
        setUrl(result.url)
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
  }, [path, workspaceRoot])

  if (loading) {
    return (
      <div className="flex min-h-0 flex-1 flex-col bg-ds-canvas">
        <EditorListSkeleton />
      </div>
    )
  }

  if (error || !url) {
    return (
      <div className="flex min-h-0 flex-1 items-center justify-center px-6 text-center text-[13px] text-ds-faint">
        {error ?? t('workspaceEditorPickFile')}
      </div>
    )
  }

  return (
    <iframe
      title={path.split(/[/\\]/).pop() ?? path}
      src={url}
      className="min-h-0 w-full flex-1 border-0 bg-ds-canvas"
    />
  )
}
