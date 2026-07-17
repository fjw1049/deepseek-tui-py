import type { ReactElement } from 'react'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useShallow } from 'zustand/react/shallow'
import { ChevronDown, Loader2 } from 'lucide-react'
import type { ChatBlock } from '../../agent/types'
import { useChatStore } from '../../store/chat-store'
import { buildTrackedProcesses, type TrackedProcess } from '../../lib/process-tracker'
import { subagentStepsToFlowItems } from '../../lib/subagent-mailbox'
import type { StepFlowItem } from './StepFlow'
import {
  WorkflowDagView,
  workflowFocusLabel,
  workflowProgressPct
} from './WorkflowDagView'

function collectSubagentStepsByAgentId(
  blocks: ChatBlock[]
): Record<string, StepFlowItem[]> {
  const out: Record<string, StepFlowItem[]> = {}
  for (const block of blocks) {
    if (block.kind !== 'subagent') continue
    if (block.cardKind === 'delegate') {
      const items = subagentStepsToFlowItems(block.steps, 0, block.status)
      if (items.length > 0) out[block.agentId] = items
      continue
    }
    for (const [workerId, steps] of Object.entries(block.workerSteps ?? {})) {
      const workerStatus = block.workers?.find((worker) => worker.id === workerId)?.status
      const items = subagentStepsToFlowItems(steps, 0, workerStatus)
      if (items.length > 0) out[workerId] = items
    }
  }
  return out
}

/**
 * Live indicator above the composer — running workflows only, showing the
 * full DAG (nodes / waves / agent steps) so users can watch orchestration
 * without opening a dialog or hunting the timeline. Terminal runs live in
 * the timeline as WorkflowBlock cards, so there is nothing to dismiss here.
 */
function WorkflowComposerPanel({
  process,
  subagentStepsByAgentId
}: {
  process: Extract<TrackedProcess, { type: 'workflow' }>
  subagentStepsByAgentId: Record<string, StepFlowItem[]>
}): ReactElement {
  const { t } = useTranslation('common')
  const { workflow } = process
  const snap = workflow.snapshot
  // Open by default so the live wave / agent / tool-step DAG is visible
  // above the input without an extra click. User can collapse.
  const [open, setOpen] = useState(true)
  const pct = process.progressPct ?? workflowProgressPct(snap)
  const focus = workflowFocusLabel(snap)
  const runId = workflow.runId?.trim()

  return (
    <section
      className="mb-2 w-full overflow-hidden rounded-[16px] border border-sky-300/55 bg-sky-500/[0.05] shadow-[0_10px_28px_rgba(15,23,42,0.06)] dark:border-sky-800/50"
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
            <Loader2 className="h-4 w-4 animate-spin" strokeWidth={2} />
          </span>
          <span className="min-w-0 flex-1">
            <span className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
              <span className="truncate text-[14px] font-semibold tracking-[-0.02em] text-ds-ink">
                {workflow.workflowName || snap.name}
              </span>
              <span className="shrink-0 rounded-full bg-black/[0.05] px-1.5 py-0.5 text-[10.5px] font-semibold text-ds-muted dark:bg-white/[0.08]">
                {t('processTrayStatusRunning')}
              </span>
              {pct != null ? (
                <span className="shrink-0 tabular-nums text-[11px] text-ds-faint">{pct}%</span>
              ) : null}
            </span>
            <span className="mt-0.5 block truncate text-[12px] text-ds-muted">
              {focus
                ? t('workflowFocusRunning', { label: focus })
                : snap.description ||
                  `${snap.done_count}/${Math.max(snap.agent_count, snap.nodes?.length ?? 0)}`}
            </span>
            {pct != null ? (
              <span className="mt-2 block h-1 overflow-hidden rounded-full bg-ds-border/80">
                <span
                  className="block h-full rounded-full bg-sky-500 transition-[width] duration-300"
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
  // Terminal runs are covered by timeline WorkflowBlock cards; the tray is a
  // live-only indicator.
  const live = processes.filter((process) => process.status === 'running')

  if (live.length === 0) return null

  return (
    <div className="ds-no-drag flex w-full flex-col gap-1.5">
      {live.map((process) => (
        <WorkflowComposerPanel
          key={process.id}
          process={process}
          subagentStepsByAgentId={subagentStepsByAgentId}
        />
      ))}
    </div>
  )
}
