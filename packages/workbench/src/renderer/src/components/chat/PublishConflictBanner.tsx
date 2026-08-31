import { useEffect, useState, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { useChatStore } from '../../store/chat-store'
import { openChangesPanel } from '../../lib/change-review'
import {
  publishAttentionState,
  publishRecoveryDecisionKey
} from './publish-conflict-state'

type Feedback = 'applied' | 'failed' | null
type RecoveryChoice = 'use_agent' | 'keep_project'
type RecoveryDecision = {
  choice: RecoveryChoice
  decisionKey: string
  recoveryToken: string | undefined
}

/**
 * User-facing delivery state for an isolated session draft.
 *
 * Worktree/checkpoint mechanics stay internal: ordinary drafts publish without
 * chrome, while recovery ambiguity, failures, and real file conflicts ask for
 * the smallest decision needed to continue.
 */
export function PublishConflictBanner(): ReactElement | null {
  const { t } = useTranslation('common')
  const activeThreadId = useChatStore((s) => s.activeThreadId)
  const busy = useChatStore((s) => s.busy)
  const resolvePublishConflicts = useChatStore((s) => s.resolvePublishConflicts)
  const warmActiveThread = useChatStore((s) => s.warmActiveThread)
  const refreshThreads = useChatStore((s) => s.refreshThreads)
  const thread = useChatStore((s) =>
    s.activeThreadId ? s.threads.find((item) => item.id === s.activeThreadId) ?? null : null
  )
  const [submitting, setSubmitting] = useState(false)
  const [feedback, setFeedback] = useState<Feedback>(null)
  const [recoveryDecision, setRecoveryDecision] = useState<RecoveryDecision | null>(null)

  useEffect(() => {
    setFeedback(null)
    setSubmitting(false)
    setRecoveryDecision(null)
  }, [activeThreadId])

  useEffect(() => {
    if (feedback !== 'applied') return
    const handle = window.setTimeout(() => setFeedback(null), 2400)
    return () => window.clearTimeout(handle)
  }, [feedback])

  const rawConflicts = thread?.publishConflicts ?? []
  const attention = publishAttentionState(
    rawConflicts,
    Boolean(thread?.publishBlocked),
    thread?.publishIssue
  )
  const conflicts = attention.conflicts
  const waiting = Boolean(thread?.publishWaitingOn || thread?.publishRequestAction)
  const needsAttention = attention.kind !== 'hidden'
  const recoveryDecisionKey = publishRecoveryDecisionKey(attention, thread?.updatedAt)

  useEffect(() => {
    // A choice is valid only for the exact issue/path snapshot the user saw.
    // This also clears a queued choice when the runtime publishes a newer state.
    setRecoveryDecision((decision) =>
      decision === null || decision.decisionKey === recoveryDecisionKey ? decision : null
    )
  }, [recoveryDecisionKey])

  if (!activeThreadId || thread?.envMode !== 'worktree') return null
  if (!needsAttention && !waiting && feedback === null) return null

  const run = async (
    action: 'apply' | 'use_agent' | 'keep_project',
    recoveryToken?: string
  ): Promise<void> => {
    if (!activeThreadId || submitting || busy || waiting) return
    const requestThreadId = activeThreadId
    setSubmitting(true)
    setFeedback(null)
    try {
      const result = await resolvePublishConflicts(action, undefined, recoveryToken)
      if (useChatStore.getState().activeThreadId !== requestThreadId) return
      if (result === null) {
        setFeedback('failed')
      } else if (result.status === 'applied') {
        setFeedback('applied')
        setRecoveryDecision(null)
      } else if (result.status !== 'queued') {
        // The path set or bytes may have changed after the confirmation was
        // shown. The backend refreshes the decision without writing; require a
        // fresh confirmation for that new snapshot.
        setRecoveryDecision(null)
      }
    } finally {
      setSubmitting(false)
    }
  }

  const chooseRecovery = (choice: RecoveryChoice): void => {
    if (recoveryDecisionKey === null) return
    setRecoveryDecision({
      choice,
      decisionKey: recoveryDecisionKey,
      recoveryToken: thread?.updatedAt
    })
  }

  const retryMissingWorkspace = async (): Promise<void> => {
    if (!activeThreadId || submitting || busy || waiting) return
    setSubmitting(true)
    setFeedback(null)
    try {
      // Warmup re-runs the backend's safe workspace preparation. It never
      // chooses a file version; if the original copy is still unavailable the
      // missing state remains unchanged.
      await warmActiveThread(activeThreadId)
      await refreshThreads()
      if (useChatStore.getState().activeThreadId !== activeThreadId) return
      const current = useChatStore
        .getState()
        .threads.find((item) => item.id === activeThreadId)
      const currentAttention = publishAttentionState(
        current?.publishConflicts ?? [],
        Boolean(current?.publishBlocked),
        current?.publishIssue
      )
      if (currentAttention.kind === 'missing') setFeedback('failed')
    } finally {
      setSubmitting(false)
    }
  }

  if (feedback === 'applied' && !needsAttention) {
    return (
      <div className="ds-no-drag mx-2 mb-2 flex items-center justify-between rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-3 py-2 text-[12px] text-emerald-700 dark:text-emerald-300 sm:mx-3">
        <span>{t('publishDraftApplied')}</span>
      </div>
    )
  }

  if (!needsAttention && waiting) {
    return (
      <div
        className="ds-no-drag mx-2 mb-2 flex items-center gap-2 px-3 py-1 text-[12px] text-ds-muted sm:mx-3"
        data-publish-waiting="true"
        role="status"
      >
        <span className="h-3 w-3 animate-spin rounded-full border border-ds-faint border-t-ds-ink" />
        <span>{t('publishDraftWaiting')}</span>
      </div>
    )
  }

  if (attention.kind === 'recovery') {
    return (
      <div
        className="ds-publish-conflict-banner mx-2 mb-2 rounded-xl border border-amber-500/25 bg-amber-500/5 px-3 py-2.5 sm:mx-3"
        data-publish-recovery-banner="true"
      >
        <p className="text-[13px] font-medium leading-5 text-ds-ink">
          {t('publishRecoveryTitle')}
        </p>
        <p className="mt-0.5 text-[12px] leading-5 text-ds-muted">
          {conflicts.length > 0
            ? t('publishRecoveryBody', { count: conflicts.length })
            : t('publishRecoveryFilesUnknown')}
        </p>
        {conflicts.length > 0 ? (
          <ul className="mt-2 max-h-28 overflow-y-auto font-mono text-[12px] leading-5 text-ds-ink">
            {conflicts.slice(0, 8).map((file) => (
              <li key={file} className="truncate" title={file}>
                {file}
              </li>
            ))}
            {conflicts.length > 8 ? (
              <li className="text-ds-muted">
                {t('publishMoreFiles', { count: conflicts.length - 8 })}
              </li>
            ) : null}
          </ul>
        ) : null}
        {waiting ? (
          <p className="mt-2 inline-flex items-center gap-2 text-[12px] text-ds-muted">
            <span className="h-3 w-3 animate-spin rounded-full border border-ds-faint border-t-ds-ink" />
            {t('publishDraftWaiting')}
          </p>
        ) : null}
        {feedback === 'failed' ? (
          <p className="mt-2 text-[12px] text-red-600 dark:text-red-300">
            {t('publishDraftFailed')}
          </p>
        ) : null}
        {recoveryDecision ? (
          <div
            className="mt-2 rounded-lg border border-amber-500/20 bg-ds-surface/70 p-2.5"
            data-publish-recovery-confirm="true"
          >
            <p className="text-[12px] leading-5 text-ds-ink">
              {recoveryDecision.choice === 'keep_project'
                ? conflicts.length > 0
                  ? t('publishRecoveryConfirmKeepProject')
                  : t('publishRecoveryConfirmKeepProjectUnknown')
                : t('publishRecoveryConfirmUseAgent')}
            </p>
            <div className="mt-2 flex flex-wrap justify-end gap-2">
              <button
                type="button"
                disabled={submitting || waiting}
                onClick={() => setRecoveryDecision(null)}
                className="rounded-md px-2.5 py-1 text-[12px] font-medium text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink disabled:opacity-50"
              >
                {t('publishRecoveryCancel')}
              </button>
              <button
                type="button"
                data-publish-recovery-action={recoveryDecision.choice}
                disabled={submitting || busy || waiting}
                onClick={() =>
                  void run(recoveryDecision.choice, recoveryDecision.recoveryToken)
                }
                className="rounded-md bg-accent px-2.5 py-1 text-[12px] font-medium text-white transition hover:brightness-110 active:scale-[0.98] disabled:opacity-50"
              >
                {submitting
                  ? t('publishDraftApplying')
                  : recoveryDecision.choice === 'keep_project'
                    ? t('publishRecoveryKeepProject')
                    : t('publishRecoveryUseAgent')}
              </button>
            </div>
          </div>
        ) : conflicts.length > 0 ? (
          <div className="mt-2 flex flex-wrap justify-end gap-2">
            <button
              type="button"
              data-publish-recovery-choice="keep_project"
              disabled={submitting || busy || waiting}
              onClick={() => chooseRecovery('keep_project')}
              className="rounded-md px-2.5 py-1 text-[12px] font-medium text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink active:scale-[0.98] disabled:opacity-50"
            >
              {t('publishRecoveryKeepProject')}
            </button>
            <button
              type="button"
              data-publish-recovery-choice="use_agent"
              disabled={submitting || busy || waiting}
              onClick={() => chooseRecovery('use_agent')}
              className="rounded-md bg-accent px-2.5 py-1 text-[12px] font-medium text-white transition hover:brightness-110 active:scale-[0.98] disabled:opacity-50"
            >
              {t('publishRecoveryUseAgent')}
            </button>
          </div>
        ) : (
          <div className="mt-2 flex justify-end">
            <button
              type="button"
              data-publish-recovery-choice="keep_project"
              disabled={submitting || busy || waiting}
              onClick={() => chooseRecovery('keep_project')}
              className="rounded-md bg-accent px-2.5 py-1 text-[12px] font-medium text-white transition hover:brightness-110 active:scale-[0.98] disabled:opacity-50"
            >
              {t('publishRecoveryKeepProject')}
            </button>
          </div>
        )}
      </div>
    )
  }

  if (attention.kind === 'missing') {
    return (
      <div className="ds-no-drag mx-2 mb-2 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-red-500/20 bg-red-500/5 px-3 py-2 sm:mx-3">
        <div className="min-w-0">
          <p className="text-[12px] font-medium leading-5 text-ds-ink">
            {t('publishMissingTitle')}
          </p>
          <p className="text-[12px] leading-5 text-ds-muted">
            {t('publishMissingBody')}
          </p>
          {feedback === 'failed' ? (
            <p
              className="mt-1 text-[12px] text-red-600 dark:text-red-300"
              data-publish-missing-retry-failed="true"
            >
              {t('publishMissingRetryFailed')}
            </p>
          ) : null}
        </div>
        {!waiting ? (
          <button
            type="button"
            data-publish-missing-retry="true"
            disabled={submitting || busy}
            onClick={() => void retryMissingWorkspace()}
            className="rounded-md bg-accent px-2.5 py-1 text-[12px] font-medium text-white transition hover:brightness-110 active:scale-[0.98] disabled:opacity-50"
          >
            {submitting ? t('publishMissingRetrying') : t('publishMissingRetry')}
          </button>
        ) : null}
      </div>
    )
  }

  if (attention.kind === 'failure') {
    return (
      <div
        className="ds-no-drag mx-2 mb-2 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-red-500/20 bg-red-500/5 px-3 py-2 sm:mx-3"
        data-publish-failure="true"
      >
        <div className="min-w-0">
          <p className="text-[12px] font-medium leading-5 text-ds-ink">
            {t('publishSyncFailedTitle')}
          </p>
          <p className="text-[12px] leading-5 text-ds-muted">
            {waiting ? t('publishDraftWaiting') : t('publishSyncFailedBody')}
          </p>
        </div>
        {!waiting ? (
          <button
            type="button"
            disabled={submitting || busy}
            onClick={() => void run('apply')}
            className="rounded-md bg-accent px-2.5 py-1 text-[12px] font-medium text-white transition hover:brightness-110 active:scale-[0.98] disabled:opacity-50"
          >
            {submitting ? t('publishDraftApplying') : t('publishSyncRetry')}
          </button>
        ) : null}
      </div>
    )
  }

  if (attention.kind !== 'conflict') return null

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
        {conflicts.length > 8 ? (
          <li className="text-ds-muted">
            {t('publishMoreFiles', { count: conflicts.length - 8 })}
          </li>
        ) : null}
      </ul>
      {feedback === 'failed' ? (
        <p className="mt-2 text-[12px] text-red-600 dark:text-red-300">
          {t('publishDraftFailed')}
        </p>
      ) : null}
      {waiting ? (
        <p className="mt-2 inline-flex items-center gap-2 text-[12px] text-ds-muted">
          <span className="h-3 w-3 animate-spin rounded-full border border-ds-faint border-t-ds-ink" />
          {t('publishDraftWaiting')}
        </p>
      ) : null}
      <div className="mt-2 flex flex-wrap justify-end gap-2">
        <button
          type="button"
          onClick={() => openChangesPanel({ context: 'conflicts' })}
          className="mr-auto rounded-md px-2.5 py-1 text-[12px] font-medium text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink active:scale-[0.98]"
        >
          {t('publishConflictReview')}
        </button>
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
