import { useEffect, useState, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { useChatStore } from '../../store/chat-store'

const UNPUBLISHED_WORKTREE_LABOR = '<unpublished-worktree-labor>'

type Feedback = 'applied' | 'failed' | null

/**
 * User-facing delivery state for an isolated session draft.
 *
 * Worktree/checkpoint mechanics stay internal: ordinary drafts get one quiet
 * apply row, waiting requests explain themselves, and only real file conflicts
 * expand into a decision card.
 */
export function PublishConflictBanner(): ReactElement | null {
  const { t } = useTranslation('common')
  const activeThreadId = useChatStore((s) => s.activeThreadId)
  const busy = useChatStore((s) => s.busy)
  const resolvePublishConflicts = useChatStore((s) => s.resolvePublishConflicts)
  const thread = useChatStore((s) =>
    s.activeThreadId ? s.threads.find((item) => item.id === s.activeThreadId) ?? null : null
  )
  const [submitting, setSubmitting] = useState(false)
  const [feedback, setFeedback] = useState<Feedback>(null)

  useEffect(() => {
    setFeedback(null)
    setSubmitting(false)
  }, [activeThreadId])

  useEffect(() => {
    if (feedback !== 'applied') return
    const handle = window.setTimeout(() => setFeedback(null), 2400)
    return () => window.clearTimeout(handle)
  }, [feedback])

  const rawConflicts = thread?.publishConflicts ?? []
  const hasRecoveredDraft = rawConflicts.includes(UNPUBLISHED_WORKTREE_LABOR)
  const conflicts = rawConflicts.filter((item) => item !== UNPUBLISHED_WORKTREE_LABOR)
  const waiting = Boolean(thread?.publishWaitingOn || thread?.publishRequestAction)
  const hasRealConflict = Boolean(thread?.publishBlocked && conflicts.length > 0)
  const hasPendingDraft = Boolean(
    thread?.publishPending || hasRecoveredDraft || hasRealConflict || waiting
  )

  if (!activeThreadId || thread?.envMode !== 'worktree') return null
  if (!hasPendingDraft && feedback === null) return null

  const run = async (
    action: 'apply' | 'use_agent' | 'keep_project'
  ): Promise<void> => {
    if (submitting || busy || waiting) return
    setSubmitting(true)
    setFeedback(null)
    try {
      const result = await resolvePublishConflicts(action)
      if (result === null) {
        setFeedback('failed')
      } else if (result.status === 'applied') {
        setFeedback('applied')
      }
    } finally {
      setSubmitting(false)
    }
  }

  if (feedback === 'applied' && !hasPendingDraft) {
    return (
      <div className="ds-no-drag mx-2 mb-2 flex items-center justify-between rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-3 py-2 text-[12px] text-emerald-700 dark:text-emerald-300 sm:mx-3">
        <span>{t('publishDraftApplied')}</span>
      </div>
    )
  }

  if (!hasRealConflict) {
    return (
      <div
        className="ds-no-drag mx-2 mb-2 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-ds-border-muted bg-ds-main/35 px-3 py-2 sm:mx-3"
        data-publish-draft-status="true"
      >
        <div className="min-w-0 text-[12px] leading-5 text-ds-muted">
          {waiting ? (
            <span className="inline-flex items-center gap-2">
              <span className="h-3 w-3 animate-spin rounded-full border border-ds-faint border-t-ds-ink" />
              {t('publishDraftWaiting')}
            </span>
          ) : submitting ? (
            t('publishDraftApplying')
          ) : feedback === 'failed' ? (
            <span className="text-red-600 dark:text-red-300">{t('publishDraftFailed')}</span>
          ) : (
            t('publishDraftPending')
          )}
        </div>
        {!waiting ? (
          <button
            type="button"
            disabled={submitting || busy}
            onClick={() => void run('apply')}
            className="rounded-md bg-accent px-2.5 py-1 text-[12px] font-medium text-white transition hover:brightness-110 active:scale-[0.98] disabled:opacity-50"
          >
            {busy ? t('publishDraftApplyAfterTurn') : t('publishDraftApply')}
          </button>
        ) : null}
      </div>
    )
  }

  return (
    <div
      className="ds-publish-conflict-banner mx-2 mb-2 rounded-xl border border-amber-500/25 bg-amber-500/5 px-3 py-2.5 sm:mx-3"
      data-publish-conflict-banner="true"
    >
      <p className="text-[13px] font-medium leading-5 text-ds-ink">
        {t('publishConflictTitle', { count: conflicts.length })}
      </p>
      <p className="mt-0.5 text-[12px] leading-5 text-ds-muted">
        {t('publishConflictBody')}
      </p>
      <ul className="mt-2 max-h-28 overflow-y-auto font-mono text-[12px] leading-5 text-ds-ink">
        {conflicts.slice(0, 8).map((file) => (
          <li key={file} className="truncate" title={file}>
            {file}
          </li>
        ))}
      </ul>
      {feedback === 'failed' ? (
        <p className="mt-2 text-[12px] text-red-600 dark:text-red-300">
          {t('publishDraftFailed')}
        </p>
      ) : null}
      <div className="mt-2 flex flex-wrap justify-end gap-2">
        <button
          type="button"
          disabled={submitting || busy || waiting}
          onClick={() => void run('keep_project')}
          className="rounded-md px-2.5 py-1 text-[12px] font-medium text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink active:scale-[0.98] disabled:opacity-50"
        >
          {t('publishConflictKeepProject')}
        </button>
        <button
          type="button"
          disabled={submitting || busy || waiting}
          onClick={() => void run('use_agent')}
          className="rounded-md bg-accent px-2.5 py-1 text-[12px] font-medium text-white transition hover:brightness-110 active:scale-[0.98] disabled:opacity-50"
        >
          {submitting ? t('publishDraftApplying') : t('publishConflictUseAgent')}
        </button>
      </div>
    </div>
  )
}
