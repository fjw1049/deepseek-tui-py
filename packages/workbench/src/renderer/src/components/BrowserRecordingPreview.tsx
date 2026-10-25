import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { FolderOpen, X } from 'lucide-react'
import { browserRequest } from './BrowserWorkspace'

export type BrowserRecording = { id: string; label: string; path: string }

export function BrowserRecordingPreview({ threadId, recording, onClose }: {
  threadId: string; recording: BrowserRecording; onClose: () => void
}) {
  const { t } = useTranslation('common')
  const dialog = useRef<HTMLDialogElement>(null)
  const [source, setSource] = useState('')
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const video = recording.id.endsWith('.webm')
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    dialog.current?.showModal()
    return () => { if (previous?.isConnected) previous.focus() }
  }, [])
  useEffect(() => {
    let disposed = false
    setSource(''); setError('')
    void browserRequest<{ image: string }>(threadId, `/artifacts/${encodeURIComponent(recording.id)}`)
      .then(result => {
        if (!result.image.startsWith(video ? 'data:video/webm;base64,' : 'data:image/gif;base64,')) throw new Error(t('browserRecordingPreviewFailed'))
        if (!disposed) setSource(result.image)
      }).catch(() => { if (!disposed) setError(t('browserRecordingPreviewFailed')) })
    return () => { disposed = true }
  }, [threadId, recording.id, video, attempt])
  return <dialog ref={dialog} className="ds-recording-preview" aria-label={t(video ? 'browserViewVideo' : 'browserViewGif')}
    onCancel={event => { event.preventDefault(); onClose() }}>
    <header><strong>{t(video ? 'browserViewVideo' : 'browserViewGif')}</strong>
      <button type="button" aria-label={t('browserRecordingPreviewClose')} onClick={onClose}><X size={18} /></button></header>
    <div className="ds-recording-preview__media">
      {error ? <div role="alert"><p>{error}</p><button type="button" onClick={() => setAttempt(value => value + 1)}>{t('browserRecordingPreviewRetry')}</button></div>
        : source ? video ? <video controls preload="metadata" src={source} onError={() => setError(t('browserRecordingPreviewFailed'))} />
          : <img src={source} alt={t('browserViewGif')} onError={() => setError(t('browserRecordingPreviewFailed'))} />
          : <p role="status">{t('browserRecordingPreviewLoading')}</p>}
    </div>
    <footer><span>{recording.id}</span><button type="button" onClick={() => {
      void window.dsGui.showItemInFolder(recording.path).catch(() => setError(t('browserRecordingFolderFailed')))
    }}><FolderOpen size={14} />{t('browserRecordingFolder')}</button></footer>
  </dialog>
}
