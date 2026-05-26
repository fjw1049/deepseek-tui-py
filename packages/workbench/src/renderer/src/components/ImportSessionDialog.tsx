import { useCallback, useEffect, useState, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { FolderOpen, Loader2, Upload, X } from 'lucide-react'
import type { TuiSessionSummary } from '@shared/ds-gui-api'
import { formatRelativeTime } from '../lib/format-relative-time'
import { useChatStore } from '../store/chat-store'

type Props = {
  open: boolean
  onClose: () => void
}

export function ImportSessionDialog({ open, onClose }: Props): ReactElement | null {
  const { t, i18n } = useTranslation('common')
  const importTuiSession = useChatStore((s) => s.importTuiSession)
  const [sessionsDir, setSessionsDir] = useState('')
  const [sessions, setSessions] = useState<TuiSessionSummary[]>([])
  const [loading, setLoading] = useState(false)
  const [importingId, setImportingId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const loadSessions = useCallback(async (): Promise<void> => {
    if (typeof window.dsGui?.listTuiSessions !== 'function') {
      setSessions([])
      setSessionsDir('')
      return
    }
    setLoading(true)
    setError(null)
    try {
      const result = await window.dsGui.listTuiSessions()
      setSessionsDir(result.dir)
      setSessions(result.sessions)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setSessions([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!open) return
    void loadSessions()
  }, [loadSessions, open])

  if (!open) return null

  const handleImport = async (input: { sessionId?: string; path?: string; title?: string }) => {
    const key = input.path ?? input.sessionId ?? 'import'
    setImportingId(key)
    setError(null)
    try {
      await importTuiSession(input)
      onClose()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setImportingId(null)
    }
  }

  const handleBrowse = async (): Promise<void> => {
    if (typeof window.dsGui?.pickTuiSessionFile !== 'function') return
    const picked = await window.dsGui.pickTuiSessionFile(sessionsDir || undefined)
    if (picked.canceled || !picked.path) return
    await handleImport({ path: picked.path })
  }

  return (
    <div className="ds-no-drag fixed inset-0 z-[80] flex items-center justify-center bg-black/35 p-4 backdrop-blur-sm">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="import-session-title"
        className="flex max-h-[min(80vh,720px)] w-full max-w-xl flex-col overflow-hidden rounded-[24px] border border-ds-border-muted/50 bg-ds-card shadow-[0_24px_80px_rgba(15,23,42,0.18)]"
      >
        <div className="flex items-start justify-between gap-3 border-b border-ds-border-muted/40 px-5 py-4">
          <div>
            <h2 id="import-session-title" className="text-[18px] font-semibold text-ds-ink">
              {t('importSessionTitle')}
            </h2>
            <p className="mt-1 text-[13px] leading-5 text-ds-muted">{t('importSessionDesc')}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-ds-faint transition hover:bg-ds-hover hover:text-ds-ink"
            aria-label={t('close')}
          >
            <X className="h-4 w-4" strokeWidth={1.8} />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          {error ? (
            <p className="mb-3 rounded-xl border border-red-300/70 bg-red-500/10 px-3 py-2 text-[13px] text-red-800 dark:border-red-800/60 dark:text-red-200">
              {error}
            </p>
          ) : null}

          {loading ? (
            <div className="flex items-center gap-2 py-8 text-[14px] text-ds-muted">
              <Loader2 className="h-4 w-4 animate-spin" />
              {t('importSessionLoading')}
            </div>
          ) : sessions.length === 0 ? (
            <div className="rounded-[18px] border border-dashed border-ds-border-muted/60 px-4 py-8 text-center">
              <p className="text-[14px] text-ds-muted">{t('importSessionEmpty')}</p>
              {sessionsDir ? (
                <p className="mt-2 truncate text-[12px] text-ds-faint" title={sessionsDir}>
                  {sessionsDir}
                </p>
              ) : null}
            </div>
          ) : (
            <ul className="space-y-2">
              {sessions.map((session) => {
                const importKey = session.path
                const busy = importingId === importKey
                return (
                  <li key={session.path}>
                    <button
                      type="button"
                      disabled={!!importingId}
                      onClick={() =>
                        void handleImport({
                          path: session.path,
                          title: session.title
                        })
                      }
                      className="flex w-full items-start gap-3 rounded-[16px] border border-ds-border-muted/45 bg-ds-elevated/50 px-3 py-3 text-left transition hover:border-accent/35 hover:bg-ds-hover/40 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-[10px] bg-accent/10 text-accent">
                        {busy ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <Upload className="h-4 w-4" strokeWidth={1.8} />
                        )}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[14px] font-medium text-ds-ink">
                          {session.title}
                        </span>
                        <span className="mt-1 block text-[12px] text-ds-muted">
                          {t('importSessionMeta', {
                            count: session.messageCount,
                            time: formatRelativeTime(session.modifiedAt, i18n.language)
                          })}
                        </span>
                        {session.workspace ? (
                          <span className="mt-1 block truncate text-[11px] text-ds-faint" title={session.workspace}>
                            {session.workspace}
                          </span>
                        ) : null}
                      </span>
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
        </div>

        <div className="flex items-center justify-between gap-3 border-t border-ds-border-muted/40 px-5 py-4">
          {sessionsDir ? (
            <p className="min-w-0 truncate text-[11px] text-ds-faint" title={sessionsDir}>
              {sessionsDir}
            </p>
          ) : (
            <span />
          )}
          <button
            type="button"
            onClick={() => void handleBrowse()}
            disabled={!!importingId}
            className="inline-flex items-center gap-2 rounded-xl border border-ds-border-muted/60 bg-white px-3 py-2 text-[13px] font-medium text-ds-ink transition hover:bg-ds-hover disabled:cursor-not-allowed disabled:opacity-60 dark:bg-ds-elevated"
          >
            <FolderOpen className="h-4 w-4" strokeWidth={1.75} />
            {t('importSessionBrowse')}
          </button>
        </div>
      </div>
    </div>
  )
}
