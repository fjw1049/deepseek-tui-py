import type { ReactElement } from 'react'
import { useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'

type Props = {
  path: string
  workspaceRoot: string
}

/** Read-only image preview for workspace editor tabs. */
export function ImageDocumentPreview({ path, workspaceRoot }: Props): ReactElement {
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
      <div className="flex min-h-0 flex-1 items-center justify-center bg-ds-sidebar">
        <Loader2 className="h-5 w-5 animate-spin text-ds-faint" strokeWidth={1.8} />
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
    <div className="flex min-h-0 flex-1 items-center justify-center overflow-auto bg-ds-sidebar p-4">
      <img
        src={url}
        alt={path.split(/[/\\]/).pop() ?? path}
        className="max-h-full max-w-full object-contain"
        draggable={false}
        onError={() => setError('Failed to load image preview.')}
      />
    </div>
  )
}
