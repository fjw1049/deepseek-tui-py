import { useState, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'

type FileRestore = {
  workspace: string
  paths: Record<string, string>
  report: { restored: string[]; merged: string[]; conflicted: string[]; skipped: string[] }
  resume_blocked: boolean
}

export function TaskFiles({ taskId, onRestored }: {
  taskId: string
  onRestored: () => void
}): ReactElement {
  const { t } = useTranslation('common')
  const [preview, setPreview] = useState<FileRestore | null>(null)
  const [applied, setApplied] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const request = async (restore: boolean): Promise<void> => {
    setBusy(true)
    setError(null)
    try {
      const path = `/v1/tasks/${encodeURIComponent(taskId)}/files${restore ? '/restore' : ''}`
      const response = await window.dsGui.runtimeRequest(path, restore ? 'POST' : 'GET')
      if (!response.ok) throw new Error(response.body || t('taskFiles.failed'))
      const result = JSON.parse(response.body) as FileRestore
      setPreview(result)
      setApplied(restore)
      if (restore) onRestored()
    } catch (err) {
      setError(err instanceof Error ? err.message : t('taskFiles.failed'))
    } finally {
      setBusy(false)
    }
  }
  return (
    <section aria-label={t('taskFiles.title')}>
      <button type="button" disabled={busy} onClick={() => void request(false)}>{t('taskFiles.title')}</button>
      {error ? <p role="alert">{error}</p> : null}
      {preview ? <>
        <p>{t('taskFiles.scope')}</p>
        <p>{preview.workspace}</p>
        {Object.keys(preview.paths).length ? <ul>
          {Object.entries(preview.paths).map(([path, status]) => <li key={path}>{path} — {t(`taskFiles.${status}`)}</li>)}
        </ul> : <p>{t('taskFiles.empty')}</p>}
        {applied ? <p role="status">{t('taskFiles.result', {
          restored: preview.report.restored.length + preview.report.merged.length,
          blocked: preview.report.conflicted.length + preview.report.skipped.length
        })}</p> : null}
        {preview.resume_blocked ? <p>{t('taskFiles.resumeBlocked')}</p> : null}
        {!applied && Object.values(preview.paths).some((s) => s === 'restored' || s === 'merged') ? <>
          <p>{t('taskFiles.confirmHint')}</p>
          <button type="button" disabled={busy} onClick={() => void request(true)}>{t('taskFiles.confirm')}</button>
        </> : null}
      </> : null}
    </section>
  )
}
