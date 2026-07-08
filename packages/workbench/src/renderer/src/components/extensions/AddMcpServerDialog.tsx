import { useEffect, useState, type ReactElement } from 'react'
import { createPortal } from 'react-dom'
import { Loader2, Plus, Trash2, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import {
  buildMcpServerEntry,
  buildSseServerEntry,
  tokenizeCommandLine,
  type McpServerEntry
} from '../../lib/mcp-json-merge'
import { normalizePluginId } from './marketplace-shared'

type EnvRow = { key: string; value: string }

type Props = {
  open: boolean
  onClose: () => void
  isDuplicate: (id: string) => boolean
  onSubmit: (id: string, entry: McpServerEntry) => Promise<void>
}

/** Parse the env rows into a record, ignoring rows with an empty key. */
function collectEnv(rows: EnvRow[]): Record<string, string> {
  const env: Record<string, string> = {}
  for (const row of rows) {
    const key = row.key.trim()
    if (key) env[key] = row.value
  }
  return env
}

export function AddMcpServerDialog({ open, onClose, isDuplicate, onSubmit }: Props): ReactElement | null {
  const { t } = useTranslation('common')
  const [type, setType] = useState<'stdio' | 'sse'>('stdio')
  const [name, setName] = useState('')
  const [command, setCommand] = useState('')
  const [url, setUrl] = useState('')
  const [timeout, setTimeout] = useState('')
  const [envRows, setEnvRows] = useState<EnvRow[]>([{ key: '', value: '' }])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!open) return
    const handleKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onClose()
      }
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [open, onClose])

  // Reset the form whenever the dialog opens.
  useEffect(() => {
    if (!open) return
    setType('stdio')
    setName('')
    setCommand('')
    setUrl('')
    setTimeout('')
    setEnvRows([{ key: '', value: '' }])
    setError(null)
    setBusy(false)
  }, [open])

  if (!open || typeof document === 'undefined') return null

  const updateEnvRow = (index: number, patch: Partial<EnvRow>): void => {
    setEnvRows((rows) => rows.map((row, i) => (i === index ? { ...row, ...patch } : row)))
  }

  // Support pasting a whole `KEY=VALUE` block into a single key cell.
  const pasteEnvKey = (index: number, text: string): boolean => {
    if (!text.includes('\n') && !text.includes('=')) return false
    const parsed = text
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => {
        const eq = line.indexOf('=')
        return eq === -1 ? { key: line, value: '' } : { key: line.slice(0, eq).trim(), value: line.slice(eq + 1).trim() }
      })
    if (parsed.length === 0) return false
    setEnvRows((rows) => {
      const next = [...rows]
      next.splice(index, 1, ...parsed)
      return next
    })
    return true
  }

  const submit = async (): Promise<void> => {
    const id = normalizePluginId(name)
    if (!id) {
      setError(t('mcpDialogNameRequired'))
      return
    }
    if (isDuplicate(id)) {
      setError(t('mcpDialogExists', { name: id }))
      return
    }
    const timeoutValue = timeout.trim() ? Number(timeout.trim()) : undefined
    const env = collectEnv(envRows)
    let entry: McpServerEntry
    if (type === 'sse') {
      if (!url.trim()) {
        setError(t('mcpDialogUrlRequired'))
        return
      }
      entry = buildSseServerEntry(url.trim(), env, timeoutValue)
    } else {
      const { command: cmd, args } = tokenizeCommandLine(command)
      if (!cmd) {
        setError(t('mcpDialogCommandRequired'))
        return
      }
      entry = buildMcpServerEntry(cmd, args, env, timeoutValue)
    }
    setBusy(true)
    setError(null)
    try {
      await onSubmit(id, entry)
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const inputClass =
    'h-10 w-full rounded-xl border border-ds-border bg-ds-main/45 px-3 text-[14px] text-ds-ink outline-none focus:border-accent/40 focus:ring-1 focus:ring-accent/30'

  return createPortal(
    <div
      className="ds-modal-backdrop ds-no-drag fixed inset-0 z-[80] flex items-center justify-center p-4"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div className="ds-content-card flex max-h-[88vh] w-full max-w-lg flex-col overflow-hidden rounded-2xl shadow-xl">
        <div className="flex shrink-0 items-center justify-between gap-3 border-b border-ds-border-muted px-5 py-3.5">
          <h2 className="min-w-0 truncate text-[16px] font-semibold text-ds-ink">{t('mcpDialogAddTitle')}</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label={t('close')}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink"
          >
            <X className="h-4 w-4" strokeWidth={1.9} />
          </button>
        </div>

        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-5 py-4">
          <div>
            <label className="mb-1.5 block text-[12px] font-medium text-ds-muted">{t('mcpDialogType')}</label>
            <select
              value={type}
              onChange={(event) => setType(event.target.value as 'stdio' | 'sse')}
              className={inputClass}
            >
              <option value="stdio">{t('mcpDialogTypeStdio')}</option>
              <option value="sse">{t('mcpDialogTypeSse')}</option>
            </select>
          </div>

          <div>
            <label className="mb-1.5 block text-[12px] font-medium text-ds-muted">{t('mcpDialogName')}</label>
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              className={inputClass}
              placeholder={t('mcpDialogNamePlaceholder')}
            />
          </div>

          {type === 'sse' ? (
            <div>
              <label className="mb-1.5 block text-[12px] font-medium text-ds-muted">{t('mcpDialogUrl')}</label>
              <input
                value={url}
                onChange={(event) => setUrl(event.target.value)}
                className={inputClass}
                placeholder={t('mcpDialogUrlPlaceholder')}
              />
            </div>
          ) : (
            <div>
              <label className="mb-1.5 block text-[12px] font-medium text-ds-muted">{t('mcpDialogCommand')}</label>
              <textarea
                value={command}
                onChange={(event) => setCommand(event.target.value)}
                className="min-h-[64px] w-full rounded-xl border border-ds-border bg-ds-main/45 px-3 py-2 font-mono text-[13px] leading-5 text-ds-ink outline-none focus:border-accent/40 focus:ring-1 focus:ring-accent/30"
                placeholder={t('mcpDialogCommandPlaceholder')}
                spellCheck={false}
              />
            </div>
          )}

          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <label className="text-[12px] font-medium text-ds-muted">{t('mcpDialogEnv')}</label>
              <span className="text-[11px] text-ds-faint">{t('mcpDialogEnvPasteHint')}</span>
            </div>
            <div className="space-y-2">
              {envRows.map((row, index) => (
                <div key={index} className="flex items-center gap-2">
                  <input
                    value={row.key}
                    onChange={(event) => updateEnvRow(index, { key: event.target.value })}
                    onPaste={(event) => {
                      const text = event.clipboardData.getData('text')
                      if (pasteEnvKey(index, text)) event.preventDefault()
                    }}
                    className="h-9 min-w-0 flex-1 rounded-lg border border-ds-border bg-ds-main/45 px-2.5 font-mono text-[12px] text-ds-ink outline-none focus:border-accent/40"
                    placeholder={t('mcpDialogEnvKey')}
                  />
                  <input
                    value={row.value}
                    onChange={(event) => updateEnvRow(index, { value: event.target.value })}
                    className="h-9 min-w-0 flex-1 rounded-lg border border-ds-border bg-ds-main/45 px-2.5 font-mono text-[12px] text-ds-ink outline-none focus:border-accent/40"
                    placeholder={t('mcpDialogEnvValue')}
                  />
                  <button
                    type="button"
                    onClick={() => setEnvRows((rows) => (rows.length > 1 ? rows.filter((_, i) => i !== index) : rows))}
                    className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink"
                    aria-label={t('skillDelete')}
                  >
                    <Trash2 className="h-4 w-4" strokeWidth={1.75} />
                  </button>
                </div>
              ))}
            </div>
            <button
              type="button"
              onClick={() => setEnvRows((rows) => [...rows, { key: '', value: '' }])}
              className="mt-2 inline-flex items-center gap-1.5 text-[12px] font-medium text-ds-muted transition hover:text-ds-ink"
            >
              <Plus className="h-3.5 w-3.5" strokeWidth={2} />
              {t('mcpDialogEnvAdd')}
            </button>
          </div>

          <div>
            <label className="mb-1.5 block text-[12px] font-medium text-ds-muted">{t('mcpDialogTimeout')}</label>
            <input
              value={timeout}
              onChange={(event) => setTimeout(event.target.value.replace(/[^0-9]/g, ''))}
              inputMode="numeric"
              className={inputClass}
              placeholder={t('mcpDialogTimeoutPlaceholder')}
            />
          </div>

          {error ? (
            <div className="rounded-xl border border-red-300/70 bg-red-50 px-3 py-2 text-[13px] text-red-800 dark:border-red-800/60 dark:bg-red-950/25 dark:text-red-200">
              {error}
            </div>
          ) : null}
        </div>

        <div className="flex shrink-0 justify-end gap-2 border-t border-ds-border-muted px-5 py-3.5">
          <button
            type="button"
            onClick={() => void submit()}
            disabled={busy}
            className="inline-flex items-center justify-center gap-2 rounded-xl bg-ds-userbubble px-4 py-2 text-[13px] font-semibold leading-none text-ds-userbubbleFg shadow-sm transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-55"
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" strokeWidth={2} /> : <Plus className="h-4 w-4" strokeWidth={2} />}
            {t('mcpDialogSubmit')}
          </button>
        </div>
      </div>
    </div>,
    document.body
  )
}
