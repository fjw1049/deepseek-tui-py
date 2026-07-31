import type { ReactElement } from 'react'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useShallow } from 'zustand/react/shallow'
import { ChevronDown, Loader2 } from 'lucide-react'
import type { ChatBlock } from '../../agent/types'
import { useChatStore } from '../../store/chat-store'
import { buildTrackedProcesses, type TrackedProcess } from '../../lib/process-tracker'
import { collectSpawnPromptsByAgentId } from '../../lib/extract-subagents-from-blocks'
import { subagentStepsToFlowItems } from '../../lib/subagent-mailbox'
import {
  clipWorkflowText,
  resolveSubtaskTitle,
  workflowFocusSubtask,
  workflowGoalText,
  workflowSubtaskProgress,
  workflowSubtasks,
  type WorkflowSubtask
} from '../../lib/workflow-subtask-view'
import type { StepFlowItem } from './StepFlow'
import { WorkflowDagView } from './WorkflowDagView'

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

/** Prefer mailbox/card prompt, then spawn-tool backfill. */
function collectSubtaskPromptsByAgentId(blocks: ChatBlock[]): Record<string, string> {
  const out = { ...collectSpawnPromptsByAgentId(blocks) }
  for (const block of blocks) {
    if (block.kind !== 'subagent') continue
    const prompt = typeof block.prompt === 'string' ? block.prompt.replace(/\s+/g, ' ').trim() : ''
    if (!prompt) continue
    out[block.agentId] = prompt
    if (block.cardKind === 'fanout' && block.workers) {
      // Fanout workers rarely carry their own prompt; keep parent as fallback only
      // when worker id has no entry yet.
      for (const worker of block.workers) {
        if (!out[worker.id]) out[worker.id] = prompt
      }
    }
  }
  return out
}

function subtaskDotClass(status: WorkflowSubtask['status']): string {
  switch (status) {
    case 'running':
      return 'border-ds-ink/40 bg-ds-ink/70'
    case 'done':
      return 'border-ds-ink/25 bg-ds-ink/40'
    case 'error':
      return 'border-ds-ink/50 bg-ds-ink/20'
    case 'skipped':
      return 'border-ds-border bg-ds-faint/40'
    default:
      return 'border-ds-border bg-transparent'
  }
}

function subtaskStatusKey(status: WorkflowSubtask['status']): string {
  switch (status) {
    case 'running':
      return 'workflowNodeRunning'
    case 'done':
      return 'workflowNodeDone'
    case 'error':
      return 'workflowNodeError'
    case 'skipped':
      return 'workflowNodeSkipped'
    default:
      return 'workflowNodeQueued'
  }
}

/**
 * Live workflow chip above the composer.
 * Titles prefer spawn prompts when controller labels are opaque ids.
 */
function WorkflowComposerPanel({
  process,
  promptsByAgentId,
  subagentStepsByAgentId
}: {
  process: Extract<TrackedProcess, { type: 'workflow' }>
  promptsByAgentId: Record<string, string>
  subagentStepsByAgentId: Record<string, StepFlowItem[]>
}): ReactElement {
  const { t } = useTranslation('common')
  const { workflow } = process
  const snap = workflow.snapshot
  const [open, setOpen] = useState(false)
  const [showDag, setShowDag] = useState(false)

  const goal = useMemo(
    () => workflowGoalText(snap, workflow.workflowName),
    [snap, workflow.workflowName]
  )
  const subtasks = useMemo(() => workflowSubtasks(snap), [snap])
  const focus = useMemo(() => workflowFocusSubtask(subtasks), [subtasks])
  const { done, total } = useMemo(() => workflowSubtaskProgress(subtasks), [subtasks])
  const showAlert = (snap.error_count ?? 0) > 0 || subtasks.some((s) => s.status === 'error')

  const focusTitle = focus
    ? resolveSubtaskTitle(focus, promptsByAgentId[focus.agentId], 56)
    : null
  const metaParts = [
    focusTitle,
    total > 0 ? t('processTraySubtaskProgress', { done, total }) : t('processTrayStatusRunning')
  ].filter(Boolean)

  return (
    <section
      className="ds-process-tray mb-1.5 w-full overflow-hidden rounded-[12px]"
      data-process-tray="workflow"
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-start gap-2 px-2.5 py-1.5 text-left transition hover:bg-ds-hover/40"
      >
        <Loader2 className="mt-0.5 h-3.5 w-3.5 shrink-0 animate-spin text-ds-ink" strokeWidth={2} />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[12.5px] font-semibold leading-5 tracking-[-0.015em] text-ds-ink">
            {goal ? clipWorkflowText(goal, 88) : t('processTrayStatusRunning')}
          </span>
          {metaParts.length > 0 ? (
            <span className="mt-0.5 block truncate text-[11.5px] leading-4 text-ds-muted">
              {metaParts.join(' · ')}
            </span>
          ) : null}
        </span>
        {showAlert ? (
          <span
            className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center text-[13px] font-semibold leading-none text-ds-ink"
            aria-hidden
          >
            !
          </span>
        ) : null}
        <ChevronDown
          className={[
            'mt-0.5 h-3.5 w-3.5 shrink-0 text-ds-muted transition-transform duration-200',
            open ? 'rotate-180' : 'rotate-0'
          ].join(' ')}
          strokeWidth={1.8}
        />
      </button>

      {open ? (
        <div className="max-h-[min(45vh,28rem)] overflow-y-auto border-t border-ds-border px-2.5 py-2">
          {goal ? (
            <p className="mb-2 px-0.5 text-[12px] leading-5 text-ds-ink">
              {clipWorkflowText(goal, 160)}
            </p>
          ) : null}

          {subtasks.length === 0 ? (
            <p className="px-0.5 text-[12px] text-ds-muted">{t('processTrayWaitingSubtasks')}</p>
          ) : (
            <ul className="flex flex-col gap-0.5">
              {subtasks.map((task) => {
                const title = resolveSubtaskTitle(task, promptsByAgentId[task.agentId], 96)
                return (
                  <li
                    key={task.agentId}
                    className="flex items-start gap-2 rounded-[8px] px-1.5 py-1"
                  >
                    {task.status === 'error' ? (
                      <span
                        className="mt-0.5 flex h-3 w-3 shrink-0 items-center justify-center text-[11px] font-semibold leading-none text-ds-ink"
                        aria-hidden
                      >
                        !
                      </span>
                    ) : (
                      <span
                        className={`mt-1 h-2 w-2 shrink-0 rounded-full border ${subtaskDotClass(task.status)} ${
                          task.status === 'running' ? 'animate-pulse' : ''
                        }`}
                      />
                    )}
                    <span className="min-w-0 flex-1">
                      <span className="block text-[12.5px] font-medium leading-5 text-ds-ink">
                        {title}
                      </span>
                      <span className="text-[11px] text-ds-muted">
                        {t(subtaskStatusKey(task.status))}
                      </span>
                    </span>
                  </li>
                )
              })}
            </ul>
          )}

          <div className="mt-2 border-t border-ds-border/70 pt-1.5">
            <button
              type="button"
              onClick={() => setShowDag((v) => !v)}
              aria-expanded={showDag}
              className="flex w-full items-center gap-1 px-0.5 text-left text-[11px] font-medium text-ds-muted transition hover:text-ds-ink"
            >
              <ChevronDown
                className={[
                  'h-3 w-3 transition-transform',
                  showDag ? 'rotate-180' : 'rotate-0'
                ].join(' ')}
                strokeWidth={1.8}
              />
              {t('processTrayDagSection')}
            </button>
            {showDag ? (
              <div className="mt-1.5">
                <WorkflowDagView
                  snapshot={snap}
                  subagentStepsByAgentId={subagentStepsByAgentId}
                />
              </div>
            ) : null}
          </div>
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
  const promptsByAgentId = useMemo(() => collectSubtaskPromptsByAgentId(blocks), [blocks])
  const live = processes.filter((process) => process.status === 'running')

  if (live.length === 0) return null

  return (
    <div className="ds-no-drag flex w-full flex-col gap-1">
      {live.map((process) => (
        <WorkflowComposerPanel
          key={process.id}
          process={process}
          promptsByAgentId={promptsByAgentId}
          subagentStepsByAgentId={subagentStepsByAgentId}
        />
      ))}
    </div>
  )
}
