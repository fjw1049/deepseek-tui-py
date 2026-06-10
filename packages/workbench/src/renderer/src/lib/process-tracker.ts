import type { ChatBlock, GoalStatusPayload } from '../agent/types'

type GoalData = NonNullable<GoalStatusPayload['goal']>
type WorkflowBlock = Extract<ChatBlock, { kind: 'workflow' }>

export type TrackedProcessStatus =
  | 'running'
  | 'waiting'
  | 'completed'
  | 'failed'
  | 'cancelled'

export type TrackedProcess =
  | {
      id: string
      type: 'goal'
      status: TrackedProcessStatus
      title: string
      subtitle: string
      progressPct: number | null
      relatedBlockIds: string[]
      goal: GoalData
    }
  | {
      id: string
      type: 'workflow'
      status: TrackedProcessStatus
      title: string
      subtitle: string
      progressPct: number | null
      relatedBlockIds: string[]
      workflow: WorkflowBlock
    }

export type BuildTrackedProcessesInput = {
  blocks: ChatBlock[]
  goalStatus: GoalStatusPayload['goal']
}

function goalStatusToProcessStatus(status: GoalData['status']): TrackedProcessStatus {
  if (status === 'active') return 'running'
  if (status === 'complete') return 'completed'
  return 'waiting'
}

function workflowStatusToProcessStatus(status: WorkflowBlock['status']): TrackedProcessStatus {
  if (status === 'completed') return 'completed'
  if (status === 'failed') return 'failed'
  if (status === 'cancelled') return 'cancelled'
  return 'running'
}

function progressPercent(done: number, total: number): number | null {
  if (total <= 0) return null
  return Math.max(0, Math.min(100, Math.round((done * 100) / total)))
}

function goalProgressPercent(goal: GoalData): number | null {
  if (!goal.token_budget || goal.token_budget <= 0) return null
  return Math.max(0, Math.min(100, Math.round((goal.tokens_used * 100) / goal.token_budget)))
}

function workflowSubtitle(block: WorkflowBlock): string {
  const snap = block.snapshot
  const progress = `${snap.done_count}/${snap.agent_count}`
  if (snap.current_phase) return `${snap.current_phase} · ${progress}`
  if (snap.error_count > 0) return `${progress} · ${snap.error_count} errors`
  if (snap.running_count > 0) return `${progress} · ${snap.running_count} running`
  return progress
}

function latestWorkflowProcesses(blocks: ChatBlock[]): TrackedProcess[] {
  const byToolCall = new Map<string, WorkflowBlock>()
  for (const block of blocks) {
    if (block.kind === 'workflow') {
      byToolCall.set(block.toolCallId, block)
    }
  }

  const workflows = [...byToolCall.values()]
  const running = workflows.filter((block) => block.status === 'running')
  const completedTail = workflows.filter((block) => block.status !== 'running').slice(-2)
  const selected = [...completedTail, ...running].filter(
    (block, index, list) => list.findIndex((candidate) => candidate.id === block.id) === index
  )

  return selected.map((block) => ({
    id: `workflow:${block.toolCallId}`,
    type: 'workflow' as const,
    status: workflowStatusToProcessStatus(block.status),
    title: block.workflowName || block.snapshot.name,
    subtitle: workflowSubtitle(block),
    progressPct: progressPercent(block.snapshot.done_count, block.snapshot.agent_count),
    relatedBlockIds: [block.id],
    workflow: block
  }))
}

export function buildTrackedProcesses({
  blocks,
  goalStatus
}: BuildTrackedProcessesInput): TrackedProcess[] {
  const processes: TrackedProcess[] = []

  if (goalStatus) {
    processes.push({
      id: `goal:${goalStatus.goal_id}`,
      type: 'goal',
      status: goalStatusToProcessStatus(goalStatus.status),
      title: goalStatus.objective,
      subtitle: goalStatus.status,
      progressPct: goalProgressPercent(goalStatus),
      relatedBlockIds: [],
      goal: goalStatus
    })
  }

  processes.push(...latestWorkflowProcesses(blocks))

  return processes
}
