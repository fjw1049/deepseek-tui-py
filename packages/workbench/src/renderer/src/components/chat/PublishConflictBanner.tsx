import { useEffect, useRef, useState, type ReactElement, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { useChatStore, useChatStoreApi } from '../../store/chat-store'
import { openChangesPanel } from '../../lib/change-review'
import { publishAttentionState, publishDecisionKey } from './publish-conflict-state'

type Feedback = 'applied' | 'failed' | 'changed' | null
type Choice = 'use_agent' | 'keep_project'
type PendingChoice = {
  choice: Choice
  decisionKey: string
  recoveryToken: string | undefined
}

const MAX_LISTED_FILES = 8

/**
 * User-facing delivery state for an isolated session draft.
 *
 * Worktree/checkpoint mechanics stay internal. Every blocking state asks one
 * plain question: which version of these files to keep, or whether to continue
 * from the project. Each choice that drops content says so once and asks for a
 * single confirmation. Opening the chat already re-checks a missing copy.
 */
export function PublishConflictBanner(): ReactElement | null {
  const chatStore = useChatStoreApi()
  const { t } = useTranslation('common')
  const activeThreadId = useChatStore((s) => s.activeThreadId)
  const busy = useChatStore((s) => s.busy)
  const resolvePublishConflicts = useChatStore((s) => s.resolvePublishConflicts)
  const thread = useChatStore((s) =>
    s.activeThreadId ? s.threads.find((item) => item.id === s.activeThreadId) ?? null : null
  )
  const [submitting, setSubmitting] = useState(false)
  const [feedback, setFeedback] = useState<Feedback>(null)
  const [pending, setPending] = useState<PendingChoice | null>(null)
  const submittingRef = useRef(false)

  useEffect(() => {
    setFeedback(null)
    setSubmitting(false)
    setPending(null)
  }, [activeThreadId])

  useEffect(() => {
    if (feedback !== 'applied') return
    const handle = window.setTimeout(() => setFeedback(null), 2400)
    return () => window.clearTimeout(handle)
  }, [feedback])

  const attention = publishAttentionState(
    thread?.publishConflicts ?? [],
    Boolean(thread?.publishBlocked),
    thread?.publishIssue
  )
  const conflicts = attention.conflicts
  const waiting = Boolean(thread?.publishWaitingOn || thread?.publishRequestAction)
  const needsAttention = attention.kind !== 'hidden'
  const decisionKey = publishDecisionKey(attention)

  useEffect(() => {
    // A confirmation answers one exact question. If the files in question
    // changed underneath it, drop it and say why instead of silently closing.
    setPending((current) => {
      if (current === null || current.decisionKey === decisionKey) return current
      if (!submittingRef.current) setFeedback('changed')
      return null
    })
  }, [decisionKey])

  if (!activeThreadId || thread?.envMode !== 'worktree') return null
  if (!needsAttention && !waiting && feedback === null) return null

  const disabled = submitting || busy || waiting

  const run = async (action: 'apply' | Choice, recoveryToken?: string): Promise<void> => {
    if (!activeThreadId || disabled) return
    const requestThreadId = activeThreadId
    submittingRef.current = true
    setSubmitting(true)
    setFeedback(null)
    try {
      const result = await resolvePublishConflicts(action, undefined, recoveryToken)
      if (chatStore.getState().activeThreadId !== requestThreadId) return
      setPending(null)
      if (result === null) setFeedback('failed')
      else if (result.status === 'applied') setFeedback('applied')
      // The runtime refused a stale choice or found new differences; the
      // banner now shows the fresh question.
      else if (result.status === 'conflict' && action !== 'apply') setFeedback('changed')
    } finally {
      submittingRef.current = false
      setSubmitting(false)
    }
  }

  const choose = (choice: Choice): void => {
    if (decisionKey === null) return
    setFeedback(null)
    setPending({ choice, decisionKey, recoveryToken: thread?.updatedAt })
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

  if (!needsAttention) return null

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
          {feedback === 'failed' ? <ErrorLine>{t('publishDraftFailed')}</ErrorLine> : null}
        </div>
        {!waiting ? (
          <PrimaryButton disabled={disabled} onClick={() => void run('apply')}>
            {submitting ? t('publishDraftApplying') : t('publishSyncRetry')}
          </PrimaryButton>
        ) : null}
      </div>
    )
  }

  // A lost copy and unidentifiable leftovers look the same to the user: the
  // project is untouched and the only way forward is to continue from it.
  const versionChoice = attention.kind !== 'missing' && conflicts.length > 0
  const confirmText = (choice: Choice): string => {
    if (!versionChoice) return t('publishRestartConfirm')
    return choice === 'keep_project'
      ? t('publishConfirmKeepProject')
      : t('publishConfirmUseAgent')
  }
  const choiceLabel = (choice: Choice): string => {
    if (!versionChoice) return t('publishRestartFromProject')
    return choice === 'keep_project'
      ? t('publishConflictKeepProject')
      : t('publishConflictUseAgent')
  }

  const notices = (
    <>
      {waiting ? (
        <p className="mt-2 inline-flex items-center gap-2 text-[12px] text-ds-muted">
          <span className="h-3 w-3 animate-spin rounded-full border border-ds-faint border-t-ds-ink" />
          {t('publishDraftWaiting')}
        </p>
      ) : null}
      {feedback === 'failed' ? <ErrorLine>{t('publishDraftFailed')}</ErrorLine> : null}
      {feedback === 'changed' ? (
        <p className="mt-2 text-[12px] text-amber-700 dark:text-amber-300" data-publish-changed="true">
          {t('publishChoiceChanged')}
        </p>
      ) : null}
    </>
  )

  const actions: ReactNode = pending ? (
    <div
      className="mt-2 rounded-lg border border-amber-500/20 bg-ds-surface/70 p-2.5"
      data-publish-confirm="true"
    >
      <p className="text-[12px] leading-5 text-ds-ink">{confirmText(pending.choice)}</p>
      <div className="mt-2 flex flex-wrap justify-end gap-2">
        <SecondaryButton disabled={submitting} onClick={() => setPending(null)}>
          {t('publishChoiceCancel')}
        </SecondaryButton>
        <PrimaryButton
          data-publish-confirm-action={pending.choice}
          disabled={disabled}
          onClick={() => void run(pending.choice, pending.recoveryToken)}
        >
          {submitting ? t('publishDraftApplying') : choiceLabel(pending.choice)}
        </PrimaryButton>
      </div>
    </div>
  ) : versionChoice ? (
    <div className="mt-2 flex flex-wrap justify-end gap-2">
      <SecondaryButton
        className="mr-auto"
        data-publish-review="true"
        onClick={() => openChangesPanel({ context: 'conflicts' })}
      >
        {t('publishConflictReview')}
      </SecondaryButton>
      <SecondaryButton
        data-publish-choice="keep_project"
        disabled={disabled}
        onClick={() => choose('keep_project')}
      >
        {t('publishConflictKeepProject')}
      </SecondaryButton>
      <PrimaryButton
        data-publish-choice="use_agent"
        disabled={disabled}
        onClick={() => choose('use_agent')}
      >
        {t('publishConflictUseAgent')}
      </PrimaryButton>
    </div>
  ) : (
    <div className="mt-2 flex justify-end">
      <PrimaryButton
        data-publish-choice="keep_project"
        disabled={disabled}
        onClick={() => choose('keep_project')}
      >
        {t('publishRestartFromProject')}
      </PrimaryButton>
    </div>
  )

  const title = versionChoice
    ? t('publishConflictTitle', { count: conflicts.length })
    : t('publishUnsyncedTitle')
  const body = versionChoice ? t('publishConflictBody') : t('publishUnsyncedBody')

  return (
    <div
      className="ds-publish-conflict-banner mx-2 mb-2 rounded-xl border border-amber-500/25 bg-amber-500/5 px-3 py-2.5 sm:mx-3"
      data-publish-choice-banner={attention.kind}
    >
      <p className="text-[13px] font-medium leading-5 text-ds-ink">{title}</p>
      <p className="mt-0.5 text-[12px] leading-5 text-ds-muted">{body}</p>
      {versionChoice ? (
        <ul className="mt-2 max-h-28 overflow-y-auto font-mono text-[12px] leading-5 text-ds-ink">
          {conflicts.slice(0, MAX_LISTED_FILES).map((file) => (
            <li key={file} className="min-w-0">
              <button
                type="button"
                title={file}
                onClick={() => openChangesPanel({ context: 'conflicts', path: file })}
                className="block w-full truncate text-left hover:text-accent hover:underline"
              >
                {file}
              </button>
            </li>
          ))}
          {conflicts.length > MAX_LISTED_FILES ? (
            <li className="text-ds-muted">
              {t('publishMoreFiles', { count: conflicts.length - MAX_LISTED_FILES })}
            </li>
          ) : null}
        </ul>
      ) : null}
      {notices}
      {actions}
    </div>
  )
}

type ButtonProps = {
  children: ReactNode
  onClick: () => void
  disabled?: boolean
  className?: string
} & { [data: `data-${string}`]: string }

function PrimaryButton({ children, onClick, disabled, className = '', ...data }: ButtonProps): ReactElement {
  return (
    <button
      type="button"
      {...data}
      disabled={disabled}
      onClick={onClick}
      className={`rounded-md bg-accent px-2.5 py-1 text-[12px] font-medium text-accent-foreground transition hover:brightness-110 active:scale-[0.98] disabled:opacity-50 ${className}`}
    >
      {children}
    </button>
  )
}

function SecondaryButton({ children, onClick, disabled, className = '', ...data }: ButtonProps): ReactElement {
  return (
    <button
      type="button"
      {...data}
      disabled={disabled}
      onClick={onClick}
      className={`rounded-md px-2.5 py-1 text-[12px] font-medium text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink active:scale-[0.98] disabled:opacity-50 ${className}`}
    >
      {children}
    </button>
  )
}

function ErrorLine({
  children,
  ...data
}: { children: ReactNode } & { [data: `data-${string}`]: string }): ReactElement {
  return (
    <p {...data} className="mt-2 text-[12px] text-red-600 dark:text-red-300">
      {children}
    </p>
  )
}
