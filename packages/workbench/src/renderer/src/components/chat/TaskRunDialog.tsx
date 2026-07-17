import { useEffect, useMemo, useState, type ReactElement, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Loader2, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { fetchTaskDetail, type TaskDetail } from '../../hooks/use-thread-tasks'
import { isActiveTaskStatus, isResumableTaskStatus, type TaskStatus } from '../../lib/extract-tasks-from-blocks'
import { timelineToFlowItems } from '../../lib/task-step-flow'
import { formatTaskDuration, TaskStatusGlyph, taskStatusLabelKey } from './task-status'
import { useChatStore } from '../../store/chat-store'
import { StepFlow } from './StepFlow'

type Props = {
  taskId: string
  initialStatus: TaskStatus
  open: boolean
  onClose: () => void
}

const POLL_MS = 1500

export function TaskRunDialog({
  taskId,
  initialStatus,
  open,
  onClose
}: Props): ReactElement | null {
  const { t } = useTranslation('common')
  const sendMessage = useChatStore((s) => s.sendMessage)
  const busy = useChatStore((s) => s.busy)
  const [detail, setDetail] = useState<TaskDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [resuming, setResuming] = useState(false)
  const [promptOpen, setPromptOpen] = useState(false)

  useEffect(() => {
    if (!open) {
      setDetail(null)
      setPromptOpen(false)
      return
    }
    let cancelled = false
    let interval: number | undefined
    const load = (): void => {
      void fetchTaskDetail(taskId).then((d) => {
        if (cancelled) return
        setDetail(d)
        setLoading(false)
        if (d && !isActiveTaskStatus(d.status) && interval !== undefined) {
          window.clearInterval(interval)
          interval = undefined
        }
      })
    }
    setLoading(true)
    load()
    if (isActiveTaskStatus(initialStatus)) {
      interval = window.setInterval(load, POLL_MS)
    }
    return () => {
      cancelled = true
      if (interval !== undefined) window.clearInterval(interval)
    }
  }, [open, taskId, initialStatus])

  useEffect(() => {
    if (!open) return
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onClose()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [open, onClose])

  const flowItems = useMemo(
    () => timelineToFlowItems(detail?.timeline ?? []),
    [detail?.timeline]
  )

  if (!open || typeof document === 'undefined') return null

  const status = detail?.status ?? initialStatus
  const active = isActiveTaskStatus(status)
  const canResume = isResumableTaskStatus(status) && !busy && !resuming
  const prompt = detail?.prompt ?? ''
  const durationLabel = formatTaskDuration(detail?.durationMs ?? null)
  const statusLabel = t(taskStatusLabelKey(status))

  const onResume = async (): Promise<void> => {
    if (!canResume) return
    setResuming(true)
    try {
      const resumePrompt = t('taskResumePrompt', { taskId })
      await sendMessage(resumePrompt, 'task')
    } finally {
      setResuming(false)
    }
  }

  return createPortal(
    <div
      className="ds-modal-backdrop ds-modal-backdrop--soft ds-no-drag fixed inset-0 z-[80] flex items-center justify-center p-4 sm:p-6"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div
        className="ds-modal-surface ds-modal-surface--solid flex max-h-[min(88vh,52rem)] w-full max-w-[40rem] flex-col overflow-hidden rounded-[22px] animate-[ds-sheet-in_280ms_cubic-bezier(0.22,1,0.36,1)] motion-reduce:animate-none"
        role="dialog"
        aria-modal="true"
        aria-label={t('contextRailTaskLog')}
      >
        <header className="relative shrink-0 px-6 pb-4 pt-5">
          <div className="flex items-start gap-3 pr-10">
            <span className="mt-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-[12px] bg-ds-hover/80 text-ds-ink/80">
              <TaskStatusGlyph status={status} />
            </span>
            <div className="min-w-0 flex-1">
              <h2 className="text-[20px] font-semibold leading-tight tracking-[-0.025em] text-ds-ink">
                {t('taskRunSheetTitle')}
              </h2>
              <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[12.5px] leading-5 text-ds-muted">
                <span className="font-mono tabular-nums text-ds-faint">{taskId}</span>
                <StatusPill tone={statusTone(status)}>{statusLabel}</StatusPill>
                {durationLabel ? (
                  <span className="tabular-nums text-ds-faint">{durationLabel}</span>
                ) : null}
              </p>
            </div>
          </div>
          <div className="absolute right-4 top-4 flex items-center gap-1.5">
            {canResume ? (
              <button
                type="button"
                disabled={!canResume}
                onClick={() => void onResume()}
                className="rounded-full bg-ds-hover px-3 py-1.5 text-[12.5px] font-semibold text-ds-ink transition active:scale-[0.97] hover:bg-ds-hover/80 disabled:opacity-45"
              >
                {resuming ? t('taskResuming') : t('taskResume')}
              </button>
            ) : null}
            <CloseButton onClick={onClose} label={t('close')} />
          </div>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 pb-6">
          <div className="flex flex-col gap-5">
            {prompt ? (
              <GroupedSection
                title={t('contextRailTaskPrompt')}
                trailing={
                  <button
                    type="button"
                    onClick={() => setPromptOpen((v) => !v)}
                    className="text-[12px] font-medium text-ds-muted transition hover:text-ds-ink"
                  >
                    {promptOpen ? t('collapse') : t('expand')}
                  </button>
                }
              >
                <p
                  className={[
                    'whitespace-pre-wrap break-words px-4 py-3 text-[13.5px] leading-6 tracking-[-0.01em] text-ds-ink',
                    promptOpen ? '' : 'line-clamp-3'
                  ].join(' ')}
                >
                  {prompt}
                </p>
              </GroupedSection>
            ) : null}

            <GroupedSection
              title={t('contextRailTaskLog')}
              trailing={
                active ? (
                  <span className="inline-flex items-center gap-1.5 text-[11.5px] text-ds-faint">
                    <Loader2 className="h-3 w-3 animate-spin" />
                    {t('contextRailTaskRunning')}
                  </span>
                ) : null
              }
            >
              <div className="px-2 py-1.5">
                {flowItems.length > 0 ? (
                  <StepFlow items={flowItems} />
                ) : loading && !detail ? (
                  <div className="flex items-center gap-2 px-2 py-4 text-[13px] text-ds-muted">
                    <Loader2 className="h-4 w-4 animate-spin" />
                    {t('contextRailTaskLoading')}
                  </div>
                ) : (
                  <p className="px-2 py-4 text-[13px] leading-5 text-ds-faint">
                    {active
                      ? t('contextRailTaskRunning')
                      : t('stepFlowEmpty')}
                  </p>
                )}
              </div>
            </GroupedSection>

            {detail?.resultSummary ? (
              <GroupedSection title={t('contextRailTaskResult')} tone="result">
                <p className="whitespace-pre-wrap break-words px-4 py-3 text-[13.5px] leading-6 text-ds-ink">
                  {detail.resultSummary}
                </p>
              </GroupedSection>
            ) : detail?.error ? (
              <GroupedSection title={t('contextRailTaskResult')} tone="error">
                <p className="whitespace-pre-wrap break-words px-4 py-3 text-[13.5px] leading-6 text-ds-ink">
                  {detail.error}
                </p>
              </GroupedSection>
            ) : null}
          </div>
        </div>
      </div>
    </div>,
    document.body
  )
}

function statusTone(
  status: TaskStatus
): 'neutral' | 'running' | 'ok' | 'danger' {
  if (status === 'running' || status === 'queued') return 'running'
  if (status === 'completed') return 'ok'
  if (status === 'failed' || status === 'timed_out') return 'danger'
  return 'neutral'
}

function StatusPill({
  children,
  tone
}: {
  children: ReactNode
  tone: 'neutral' | 'running' | 'ok' | 'danger'
}): ReactElement {
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-ds-hover/70 px-2 py-0.5 text-[11px] font-semibold tracking-[0.01em] text-ds-muted">
      {children}
      {tone === 'danger' ? (
        <span className="text-[12px] font-semibold leading-none text-ds-ink/70" aria-hidden>
          !
        </span>
      ) : null}
    </span>
  )
}

function CloseButton({
  onClick,
  label
}: {
  onClick: () => void
  label: string
}): ReactElement {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex h-8 w-8 items-center justify-center rounded-full bg-black/[0.06] text-ds-muted transition active:scale-95 hover:bg-black/[0.1] hover:text-ds-ink dark:bg-white/[0.08] dark:hover:bg-white/[0.12]"
      aria-label={label}
    >
      <X className="h-3.5 w-3.5" strokeWidth={2} />
    </button>
  )
}

function GroupedSection({
  title,
  trailing,
  children,
  tone = 'default'
}: {
  title: string
  trailing?: ReactNode
  children: ReactNode
  tone?: 'default' | 'result' | 'error'
}): ReactElement {
  return (
    <section>
      <div className="mb-2 flex items-baseline justify-between gap-2 px-1">
        <h3 className="flex items-center gap-1.5 text-[12px] font-semibold tracking-[0.02em] text-ds-muted">
          {title}
          {tone === 'error' ? (
            <span className="text-[12px] font-semibold leading-none text-ds-ink/70" aria-hidden>
              !
            </span>
          ) : null}
        </h3>
        {trailing}
      </div>
      <div className="overflow-hidden rounded-[16px] border border-ds-border/70 bg-ds-card/55">
        {children}
      </div>
    </section>
  )
}
