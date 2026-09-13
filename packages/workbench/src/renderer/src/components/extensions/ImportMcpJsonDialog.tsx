import { formatRuntimeError } from '../../lib/format-runtime-error'
import { useEffect, useRef, useState, type ReactElement } from 'react'
import { createPortal } from 'react-dom'
import { Loader2, Upload, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import {
  extractMcpServersFromDocument,
  parseMcpConfigDocument,
  type McpServerEntry
} from '../../lib/mcp-json-merge'

type Props = {
  open: boolean
  onClose: () => void
  isDuplicate: (id: string) => boolean
  onSubmit: (id: string, entry: McpServerEntry) => Promise<void>
}

export function ImportMcpJsonDialog({ open, onClose, isDuplicate, onSubmit }: Props): ReactElement | null {
  const { t } = useTranslation('common')
  const [text, setText] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<{ added: number; skipped: number; failures: Array<{ id: string; entry: McpServerEntry; message: string }> } | null>(null)
  const [busy, setBusy] = useState(false)
  const submitting = useRef(false)

  useEffect(() => {
    if (!open) return
    const handleKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape' && !busy) {
        event.preventDefault()
        onClose()
      }
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [open, onClose, busy])

  useEffect(() => {
    if (!open) return
    setText('')
    setResult(null)
    setError(null)
    setBusy(false)
  }, [open])

  if (!open || typeof document === 'undefined') return null

  const submit = async (retry = false): Promise<void> => {
    if (submitting.current) return
    let servers: Record<string, McpServerEntry>
    try {
      servers = extractMcpServersFromDocument(parseMcpConfigDocument(text))
    } catch {
      setError(t('mcpImportParseError'))
      return
    }
    const entries = retry && result ? result.failures.map(({ id, entry }) => [id, entry] as const) : Object.entries(servers)
    if (entries.length === 0) {
      setError(t('mcpImportEmpty'))
      return
    }
    submitting.current = true
    setBusy(true)
    setError(null)
    let added = retry ? result?.added ?? 0 : 0
    let skipped = retry ? result?.skipped ?? 0 : 0
    const failures: Array<{ id: string; entry: McpServerEntry; message: string }> = []
    for (const [id, entry] of entries) {
      if (isDuplicate(id)) {
        skipped += 1
        continue
      }
      try {
        await onSubmit(id, entry)
        added += 1
      } catch (error) {
        failures.push({ id, entry, message: formatRuntimeError(error) })
      }
    }
    submitting.current = false
    setBusy(false)
    setResult({ added, skipped, failures })
  }

  return createPortal(
    <div
      className="ds-modal-backdrop ds-no-drag fixed inset-0 z-[80] flex items-center justify-center p-4"
      onClick={(event) => {
        if (event.target === event.currentTarget && !busy) onClose()
      }}
    >
      <div className="ds-content-card flex max-h-[88vh] w-full max-w-lg flex-col overflow-hidden rounded-2xl shadow-xl">
        <div className="flex shrink-0 items-center justify-between gap-3 border-b border-ds-border-muted px-5 py-3.5">
          <h2 className="min-w-0 truncate text-[16px] font-semibold text-ds-ink">{t('mcpImportTitle')}</h2>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            aria-label={t('close')}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink"
          >
            <X className="h-4 w-4" strokeWidth={1.9} />
          </button>
        </div>

        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-5 py-4">
          <textarea
            value={text}
            disabled={busy}
            onChange={(event) => { setText(event.target.value); setResult(null); setError(null) }}
            className="min-h-[220px] w-full rounded-xl border border-ds-border bg-ds-main/45 px-3 py-2 font-mono text-[13px] leading-5 text-ds-ink outline-none focus:border-accent/40 focus:ring-1 focus:ring-accent/30"
            placeholder={t('mcpImportPlaceholder')}
            spellCheck={false}
          />
          {result ? (
            <div role={result.failures.length ? 'alert' : 'status'} className="rounded-xl border border-ds-border p-3 text-[13px] text-ds-ink">
              <p>{t('mcpImportSummary', { added: result.added, skipped: result.skipped, failed: result.failures.length })}</p>
              {result.failures.map(({ id, message }) => <p key={id} className="mt-1 break-words text-ds-danger">{id}: {message}</p>)}
              {result.failures.length ? <button type="button" disabled={busy} className="mt-2 underline" onClick={() => void submit(true)}>{t('mcpImportRetryFailed')}</button> : null}
            </div>
          ) : null}
          {error ? (
            <div role="alert" className="rounded-xl border border-red-300/70 bg-red-50 px-3 py-2 text-[13px] text-red-800 dark:border-red-800/60 dark:bg-red-950/25 dark:text-red-200">
              {error}
            </div>
          ) : null}
        </div>

        <div className="flex shrink-0 justify-end gap-2 border-t border-ds-border-muted px-5 py-3.5">
          <button
            type="button"
            onClick={() => void submit()}
            disabled={busy || Boolean(result)}
            className="inline-flex items-center justify-center gap-2 rounded-xl bg-ds-userbubble px-4 py-2 text-[13px] font-semibold leading-none text-ds-userbubbleFg shadow-sm transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-55"
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" strokeWidth={2} /> : <Upload className="h-4 w-4" strokeWidth={2} />}
            {t('mcpImportSubmit')}
          </button>
        </div>
      </div>
    </div>,
    document.body
  )
}
