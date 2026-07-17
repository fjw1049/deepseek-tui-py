import { useState, type ReactElement } from 'react'
import { ChevronDown, Loader2, Workflow } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { WorkflowSnapshotPayload } from '../../lib/workflow-snapshot'
import { useChatStore } from '../../store/chat-store'
import type { StepFlowItem } from './StepFlow'
import {
  WorkflowDagView,
  workflowFocusLabel,
  workflowProgressPct
} from './WorkflowDagView'

export function WorkflowBlock({
  workflowName,
  status,
  snapshot,
  runId,
  subagentStepsByAgentId
}: {
  workflowName: string
  status: 'running' | 'completed' | 'failed' | 'cancelled' | 'timed_out'
  snapshot: WorkflowSnapshotPayload
  runId?: string
  /** Live tool-step rails joined into DAG agent rows by agent_id. */
  subagentStepsByAgentId?: Record<string, StepFlowItem[]>
}): ReactElement {
  const { t } = useTranslation('common')
  const sendMessage = useChatStore((s) => s.sendMessage)
  const busy = useChatStore((s) => s.busy)
  // Collapsed by default — expand for the DAG; keeps the timeline calm when
  // many workflows / large graphs are in play.
  const [expanded, setExpanded] = useState(false)
  const [resuming, setResuming] = useState(false)

  const name = workflowName || snapshot.name
  const running = status === 'running'
  const pct = workflowProgressPct(snapshot)
  const focus = workflowFocusLabel(snapshot)
  const showAlert =
    status === 'failed' || status === 'timed_out' || snapshot.error_count > 0

  const header =
    status === 'completed'
      ? t('workflowCompleted')
      : status === 'cancelled'
        ? t('workflowCancelled')
        : status === 'timed_out'
          ? t('workflowTimedOut')
          : status === 'running'
            ? t('workflowRunning')
            : t('workflowFailed')

  const stateLine =
    snapshot.error_count > 0
      ? t('workflowErrors', {
          done: snapshot.done_count,
          total: Math.max(snapshot.agent_count, snapshot.nodes?.length ?? 0),
          errors: snapshot.error_count
        })
      : t('workflowProgress', {
          done: snapshot.done_count,
          total: Math.max(snapshot.agent_count, snapshot.nodes?.length ?? 0)
        })

  const canResume =
    Boolean(runId) &&
    (status === 'cancelled' || status === 'failed' || status === 'timed_out') &&
    !busy &&
    !resuming

  const onResume = async (): Promise<void> => {
    if (!runId || !canResume) return
    setResuming(true)
    try {
      const prompt = t('workflowResumePrompt', { runId })
      await sendMessage(prompt, 'workflow')
    } finally {
      setResuming(false)
    }
  }

  return (
    <div className="overflow-hidden rounded-[14px] border border-ds-border-muted/70 bg-ds-card/55 text-[12.5px] leading-5 shadow-[0_8px_24px_rgba(15,23,42,0.04)]">
      <div className="flex items-start gap-1 px-2.5 py-2">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          className="flex min-w-0 flex-1 items-start gap-2.5 text-left transition hover:opacity-95"
        >
          <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-[10px] bg-ds-hover/80 text-ds-ink/80">
            {running ? (
              <Loader2 className="h-4 w-4 animate-spin" strokeWidth={1.9} />
            ) : (
              <Workflow className="h-4 w-4" strokeWidth={1.8} />
            )}
          </span>
          <span className="min-w-0 flex-1">
            <span className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
              <span className="truncate text-[13.5px] font-semibold tracking-[-0.015em] text-ds-ink">
                {name}
              </span>
              <span className="shrink-0 rounded-full bg-black/[0.05] px-1.5 py-0.5 text-[10.5px] font-semibold text-ds-muted dark:bg-white/[0.08]">
                {header}
              </span>
            </span>
            <span className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11.5px] text-ds-faint">
              <span className="tabular-nums">{stateLine}</span>
              {focus ? (
                <>
                  <span aria-hidden>·</span>
                  <span className="truncate text-ds-muted">
                    {running ? t('workflowFocusRunning', { label: focus }) : focus}
                  </span>
                </>
              ) : null}
            </span>
            {pct != null ? (
              <span className="mt-2 block h-1 overflow-hidden rounded-full bg-ds-border/80">
                <span
                  className="block h-full rounded-full bg-ds-ink/55 transition-[width] duration-300 dark:bg-ds-ink/70"
                  style={{ width: `${Math.min(100, Math.max(0, pct))}%` }}
                />
              </span>
            ) : null}
          </span>
          {showAlert ? (
            <span
              className="mt-1.5 flex h-5 w-5 shrink-0 items-center justify-center text-[15px] font-semibold leading-none tracking-tight text-ds-ink/70"
              aria-label={header}
              title={header}
            >
              !
            </span>
          ) : null}
          <ChevronDown
            className={[
              'mt-1.5 h-4 w-4 shrink-0 text-ds-faint transition-transform duration-200',
              expanded ? 'rotate-180' : 'rotate-0'
            ].join(' ')}
            strokeWidth={1.8}
          />
        </button>

        {canResume ? (
          <button
            type="button"
            disabled={!canResume}
            onClick={() => void onResume()}
            className="mt-0.5 shrink-0 rounded-full bg-ds-hover px-2.5 py-1 text-[11.5px] font-semibold text-ds-ink transition active:scale-[0.97] hover:bg-ds-hover/80 disabled:opacity-45"
          >
            {resuming ? t('workflowResuming') : t('workflowResume')}
          </button>
        ) : null}
      </div>

      {expanded ? (
        <div className="border-t border-ds-border/45 px-2.5 py-2.5">
          {runId ? (
            <p className="mb-2 truncate px-1 font-mono text-[10px] text-ds-faint">{runId}</p>
          ) : null}
          {snapshot.description ? (
            <p className="mb-2 px-1 text-[12px] leading-5 text-ds-muted">{snapshot.description}</p>
          ) : null}
          <WorkflowDagView snapshot={snapshot} subagentStepsByAgentId={subagentStepsByAgentId} />
        </div>
      ) : null}
    </div>
  )
}
