import type { ReactElement } from 'react'
import { useEffect, useState } from 'react'
import { Info } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useChatStore } from '../store/chat-store'
import { formatRelativeTimeCompact } from '../lib/format-relative-time'
import { shouldShowWorkspaceInHeader, workspaceLabelFromPath } from '../lib/workspace-label'

type Props = {
  compact?: boolean
  className?: string
}

export function SessionHeader({ compact = false, className = '' }: Props): ReactElement {
  const { t, i18n } = useTranslation('common')
  const threads = useChatStore((s) => s.threads)
  const activeThreadId = useChatStore((s) => s.activeThreadId)
  const busy = useChatStore((s) => s.busy)
  const workspaceLabel = useChatStore((s) => s.workspaceLabel)
  const workspaceRoot = useChatStore((s) => s.workspaceRoot)
  const showWorkspaceMeta = shouldShowWorkspaceInHeader(workspaceRoot)
  const renameActiveThread = useChatStore((s) => s.renameActiveThread)

  const active = threads.find((th) => th.id === activeThreadId)
  const activeWorkspaceLabel = active?.workspace
    ? workspaceLabelFromPath(active.workspace)
    : workspaceLabel
  const [editing, setEditing] = useState(false)
  const [draftTitle, setDraftTitle] = useState('')

  useEffect(() => {
    if (active) {
      setDraftTitle(active.title)
    } else {
      setDraftTitle('')
    }
    setEditing(false)
  }, [active])

  const commitTitle = (): void => {
    if (!active) {
      setEditing(false)
      return
    }
    const next = draftTitle.trim()
    if (!next || next === active.title) {
      setDraftTitle(active.title)
      setEditing(false)
      return
    }
    void renameActiveThread(next).finally(() => setEditing(false))
  }

  if (compact) {
    return (
      <div
        className={`ds-session-header ds-no-drag flex min-h-0 min-w-0 flex-1 items-center gap-1 text-left ${className}`}
      >
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-[6px] border border-ds-border-muted/70 bg-ds-elevated/45 text-ds-faint shadow-[inset_0_1px_0_rgba(255,255,255,0.45)] dark:border-white/10 dark:bg-white/5 dark:shadow-[inset_0_1px_0_rgba(255,255,255,0.05)]">
          <Info
            className="h-2.5 w-2.5 shrink-0 opacity-90"
            strokeWidth={2}
            aria-hidden
          />
        </span>
        {active ? (
          <div className="min-w-0 flex-1 overflow-hidden">
            <div
              className="ds-session-header-meta flex min-w-0 flex-wrap items-center gap-x-1 gap-y-0 text-[9.5px] leading-3 text-ds-faint"
              title={active.title}
            >
              <span className="max-w-[min(42vw,240px)] truncate">{activeWorkspaceLabel}</span>
              <span className="opacity-70">·</span>
              <span className="shrink-0 capitalize">{active.mode}</span>
              <span className="opacity-70">·</span>
              <span className="shrink-0 tabular-nums">
                {formatRelativeTimeCompact(active.updatedAt)}
              </span>
            </div>
          </div>
        ) : showWorkspaceMeta ? (
          <div className="min-w-0 overflow-hidden">
            <div className="truncate text-[9.5px] leading-3 font-medium text-ds-faint">{workspaceLabel}</div>
          </div>
        ) : null}
      </div>
    )
  }

  return (
    <div className={`ds-session-header ds-no-drag flex min-h-[74px] min-w-0 flex-1 items-center gap-4 px-5 py-4 sm:px-6 ${className}`}>
      {active ? (
        <>
          <div className="min-w-0 flex-1">
            <div className="ds-session-header-meta mb-1 flex min-w-0 items-center gap-2 text-[12.5px] font-medium text-ds-faint">
              <span>{activeWorkspaceLabel}</span>
              <span>·</span>
              <span className="capitalize">{active.mode}</span>
              <span>·</span>
              <span>{formatRelativeTimeCompact(active.updatedAt)}</span>
            </div>
            <div className="flex min-w-0 items-center gap-2.5">
              {editing ? (
                <input
                  className="ds-session-header-title min-w-0 flex-1 rounded-2xl border border-ds-border bg-ds-elevated px-3.5 py-2 text-[21px] font-semibold tracking-[-0.02em] text-ds-ink focus:border-accent/40 focus:outline-none focus:ring-1 focus:ring-accent/20"
                  value={draftTitle}
                  onChange={(e) => setDraftTitle(e.target.value)}
                  onBlur={() => commitTitle()}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault()
                      commitTitle()
                    }
                    if (e.key === 'Escape') {
                      setDraftTitle(active.title)
                      setEditing(false)
                    }
                  }}
                  aria-label={t('renameThreadHint')}
                  autoFocus
                />
              ) : (
                <button
                  type="button"
                  className="ds-session-header-title min-w-0 truncate text-left text-[22px] font-semibold tracking-[-0.03em] text-ds-ink transition hover:text-accent"
                  title={t('renameThreadHint')}
                  onClick={() => setEditing(true)}
                >
                  {active.title}
                </button>
              )}
            </div>
            <div className="mt-2 flex min-w-0 flex-wrap items-center gap-2 text-[12.5px] text-ds-faint">
              <span className="inline-flex items-center rounded-full border border-ds-border bg-ds-subtle px-2.5 py-1 font-medium capitalize text-ds-muted">
                {active.mode}
              </span>
              {active.workspace ? (
                <span className="truncate rounded-full border border-ds-border bg-ds-card/70 px-2.5 py-1">
                  {active.workspace.split(/[/\\]/).pop()}
                </span>
              ) : null}
            </div>
          </div>
        </>
      ) : (
        <div className="min-w-0">
          {showWorkspaceMeta ? (
            <div className="text-[12.5px] font-medium uppercase tracking-[0.16em] text-ds-faint">
              {workspaceLabel}
            </div>
          ) : null}
          <div className={`${showWorkspaceMeta ? 'mt-1' : ''} text-[20px] font-semibold tracking-[-0.02em] text-ds-ink`}>
            {t('newChat')}
          </div>
          <div className="ds-session-header-hint mt-1 text-[13.5px] text-ds-faint">{t('sessionHeaderHint')}</div>
        </div>
      )}
      {busy ? (
        <span className="ml-auto shrink-0 rounded-full bg-amber-500/18 px-3 py-1.5 text-[12.5px] font-semibold text-amber-950 dark:text-amber-100">
          {t('running')}
        </span>
      ) : null}
    </div>
  )
}
