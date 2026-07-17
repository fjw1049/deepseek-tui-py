import type { ReactElement } from 'react'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useShallow } from 'zustand/react/shallow'
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  Loader2,
  Pause,
  Workflow,
  X
} from 'lucide-react'
import type { ChatBlock } from '../../agent/types'
import { useChatStore } from '../../store/chat-store'
import {
  buildTrackedProcesses,
  type TrackedProcess,
  type TrackedProcessStatus
} from '../../lib/process-tracker'
import { subagentStepsToFlowItems } from '../../lib/subagent-mailbox'
import type { StepFlowItem } from './StepFlow'
import {
  WorkflowDagView,
  workflowFocusLabel,
  workflowProgressPct
} from './WorkflowDagView'

function statusLabel(status: TrackedProcessStatus, t: (key: string) => string): string {
  if (status === 'running') return t('processTrayStatusRunning')
  if (status === 'waiting') return t('processTrayStatusWaiting')
  if (status === 'completed') return t('processTrayStatusCompleted')
  if (status === 'failed') return t('processTrayStatusFailed')
  return t('processTrayStatusCancelled')
}

function collectSubagentStepsByAgentId(
  blocks: ChatBlock[]
): Record<string, StepFlowItem[]> {
  const out: Record<string, StepFlowItem[]> = {}
  for (const block of blocks) {
    if (block.kind !== 'subagent') continue
    if (block.cardKind === 'delegate') {
      const items = subagentStepsToFlowItems(block.steps)
      if (items.length > 0) out[block.agentId] = items
      continue
    }
    for (const [workerId, steps] of Object.entries(block.workerSteps ?? {})) {
      const items = subagentStepsToFlowItems(steps)
      if (items.length > 0) out[workerId] = items
    }
  }
  return out
}

function StatusIcon({ status }: { status: TrackedProcessStatus }): ReactElement {
  if (status === 'running') {
    return <Loader2 className="h-4 w-4 animate-spin" strokeWidth={2} />
  }
  if (status === 'completed') {
    return <CheckCircle2 className="h-4 w-4" strokeWidth={1.9} />
  }
  if (status === 'failed') {
    return <AlertTriangle className="h-4 w-4" strokeWidth={1.9} />
  }
  return <Pause className="h-4 w-4" strokeWidth={1.9} />
}

function toneFor(status: TrackedProcessStatus): string {
  if (status === 'failed') {
    return 'border-rose-300/55 bg-rose-500/[0.05] dark:border-rose-800/50'
  }
  if (status === 'completed') {
    return 'border-emerald-300/45 bg-emerald-500/[0.04] dark:border-emerald-800/45'
  }
  if (status === 'cancelled' || status === 'waiting') {
    return 'border-amber-300/50 bg-amber-500/[0.05] dark:border-amber-800/45'
  }
  return 'border-sky-300/55 bg-sky-500/[0.05] dark:border-sky-800/50'
}

/**
 * Inline workflow panel above the composer — not a modal. Shows the full DAG
 * (nodes / waves / agent steps) so users can watch orchestration without
 * opening a dialog or hunting the timeline.
 */
function WorkflowComposerPanel({
  process,
  subagentStepsByAgentId,
  onDismiss
}: {
  process: Extract<TrackedProcess, { type: 'workflow' }>
  subagentStepsByAgentId: Record<string, StepFlowItem[]>
  onDismiss: () => void
}): ReactElement {
  const { t } = useTranslation('common')
  const sendMessage = useChatStore((s) => s.sendMessage)
  const busy = useChatStore((s) => s.busy)
  const { workflow } = process
  const snap = workflow.snapshot
  const running = process.status === 'running'
  // Open by default so the full wave / agent / tool-step DAG is visible
  // above the input without an extra click. User can collapse; dismiss (X)
  // removes terminal panels.
  const [open, setOpen] = useState(true)
  const pct = process.progressPct ?? workflowProgressPct(snap)
  const focus = workflowFocusLabel(snap)
  const runId = workflow.runId?.trim()
  const canResume =
    Boolean(runId) &&
    (workflow.status === 'cancelled' ||
      workflow.status === 'failed' ||
      workflow.status === 'timed_out') &&
    !busy

  return (
    <section
      className={[
        'mb-2 w-full overflow-hidden rounded-[16px] border shadow-[0_10px_28px_rgba(15,23,42,0.06)]',
        toneFor(process.status)
      ].join(' ')}
      data-process-tray="workflow"
    >
      <div className="flex items-start gap-2 px-3 py-2.5">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className="flex min-w-0 flex-1 items-start gap-2.5 text-left"
        >
          <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-[10px] bg-sky-500/14 text-sky-700 dark:text-sky-300">
            {running ? (
              <StatusIcon status={process.status} />
            ) : (
              <Workflow className="h-4 w-4" strokeWidth={1.8} />
            )}
          </span>
          <span className="min-w-0 flex-1">
            <span className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
              <span className="truncate text-[14px] font-semibold tracking-[-0.02em] text-ds-ink">
                {workflow.workflowName || snap.name}
              </span>
              <span className="shrink-0 rounded-full bg-black/[0.05] px-1.5 py-0.5 text-[10.5px] font-semibold text-ds-muted dark:bg-white/[0.08]">
                {statusLabel(process.status, t)}
              </span>
              {pct != null ? (
                <span className="shrink-0 tabular-nums text-[11px] text-ds-faint">{pct}%</span>
              ) : null}
            </span>
            <span className="mt-0.5 block truncate text-[12px] text-ds-muted">
              {focus
                ? running
                  ? t('workflowFocusRunning', {
                      defaultValue: 'now {{label}}',
                      label: focus
                    })
                  : focus
                : snap.description ||
                  `${snap.done_count}/${Math.max(snap.agent_count, snap.nodes?.length ?? 0)}`}
            </span>
            {pct != null ? (
              <span className="mt-2 block h-1 overflow-hidden rounded-full bg-ds-border/80">
                <span
                  className={[
                    'block h-full rounded-full transition-[width] duration-300',
                    process.status === 'failed'
                      ? 'bg-rose-500'
                      : process.status === 'completed'
                        ? 'bg-emerald-500'
                        : 'bg-sky-500'
                  ].join(' ')}
                  style={{ width: `${Math.min(100, Math.max(0, pct))}%` }}
                />
              </span>
            ) : null}
          </span>
          <ChevronDown
            className={[
              'mt-1.5 h-4 w-4 shrink-0 text-ds-faint transition-transform duration-200',
              open ? 'rotate-180' : 'rotate-0'
            ].join(' ')}
            strokeWidth={1.8}
          />
        </button>

        <div className="flex shrink-0 items-center gap-1">
          {canResume && runId ? (
            <button
              type="button"
              onClick={() => {
                const prompt = t('workflowResumePrompt', {
                  defaultValue:
                    '请用 workflow 工具【只传 run_id】续跑被中断的工作流 {{runId}}。不要重新用 name+task 开新跑；从 checkpoint 跳过已完成步骤继续。',
                  runId
                })
                void sendMessage(prompt, 'workflow')
              }}
              className="rounded-full bg-sky-500/12 px-2.5 py-1 text-[11.5px] font-semibold text-sky-800 transition hover:bg-sky-500/18 dark:text-sky-200"
            >
              {t('workflowResume', { defaultValue: '续跑' })}
            </button>
          ) : null}
          {!running ? (
            <button
              type="button"
              onClick={onDismiss}
              aria-label={t('close')}
              className="flex h-7 w-7 items-center justify-center rounded-full text-ds-faint transition hover:bg-ds-hover hover:text-ds-ink"
            >
              <X className="h-3.5 w-3.5" strokeWidth={1.9} />
            </button>
          ) : null}
        </div>
      </div>

      {open ? (
        <div className="max-h-[min(55vh,32rem)] overflow-y-auto border-t border-ds-border/45 px-2.5 py-2">
          {runId ? (
            <p className="mb-1.5 truncate px-1 font-mono text-[10px] text-ds-faint">{runId}</p>
          ) : null}
          {snap.description ? (
            <p className="mb-2 px-1 text-[12px] leading-5 text-ds-muted">{snap.description}</p>
          ) : null}
          <WorkflowDagView
            snapshot={snap}
            subagentStepsByAgentId={subagentStepsByAgentId}
          />
        </div>
      ) : null}
    </section>
  )
}

export function ProcessTray(): ReactElement | null {
  const blocks = useChatStore(useShallow((s) => s.blocks))
  const processes = useMemo(() => buildTrackedProcesses({ blocks }), [blocks])
  const subagentStepsByAgentId = useMemo(
    () => collectSubagentStepsByAgentId(blocks),
    [blocks]
  )
  const [dismissedIds, setDismissedIds] = useState<Set<string>>(() => new Set())

  const visible = processes.filter((process) => {
    if (process.status === 'running') return true
    return !dismissedIds.has(process.id)
  })

  if (visible.length === 0) return null

  return (
    <div className="ds-no-drag flex w-full flex-col gap-1.5">
      {visible.map((process) => (
        <WorkflowComposerPanel
          key={process.id}
          process={process}
          subagentStepsByAgentId={subagentStepsByAgentId}
          onDismiss={() =>
            setDismissedIds((prev) => {
              const next = new Set(prev)
              next.add(process.id)
              return next
            })
          }
        />
      ))}
    </div>
  )
}
