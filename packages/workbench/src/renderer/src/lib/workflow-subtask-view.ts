import type { WorkflowAgentRun, WorkflowSnapshotPayload } from './workflow-snapshot'

export type WorkflowSubtaskStatus = WorkflowAgentRun['status']

export type WorkflowSubtask = {
  agentId: string
  /** Controller spawn label — often a short id like a_engine. */
  label: string
  status: WorkflowSubtaskStatus
  stepId: string
  resultPreview?: string | null
  error?: string | null
}

/** Engine shell labels — not user-facing subtask titles. */
const SHELL_LABEL_RE = /^(?:orchestrate|adaptive|dynamic(?::.+)?)$/i

/** Opaque controller ids: a_engine, pkg_workbench, step_3 — not a sentence. */
const OPAQUE_LABEL_RE = /^[a-z][a-z0-9]*(?:_[a-z0-9]+){0,4}$/i

export function isWorkflowShellLabel(label: string | null | undefined): boolean {
  const trimmed = label?.trim() ?? ''
  if (!trimmed) return true
  return SHELL_LABEL_RE.test(trimmed)
}

export function isOpaqueSubtaskLabel(label: string | null | undefined): boolean {
  const trimmed = label?.trim() ?? ''
  if (!trimmed) return true
  if (isWorkflowShellLabel(trimmed)) return true
  // Human labels usually have spaces / CJK / punctuation.
  if (/[\s\u3400-\u9fff，。！？、；：]/.test(trimmed)) return false
  if (trimmed.length <= 28 && OPAQUE_LABEL_RE.test(trimmed)) return true
  return false
}

export function clipWorkflowText(text: string, maxChars: number): string {
  const oneLine = text.replace(/\s+/g, ' ').trim()
  if (!oneLine) return ''
  if (oneLine.length <= maxChars) return oneLine
  return `${oneLine.slice(0, Math.max(maxChars - 1, 1)).trimEnd()}…`
}

/** Goal = workflow tool `task` → snapshot.description; else preset name. */
export function workflowGoalText(
  snapshot: WorkflowSnapshotPayload,
  workflowName?: string
): string {
  const description = snapshot.description?.trim()
  if (description && !isWorkflowShellLabel(description)) return description
  const name = (workflowName || snapshot.name || '').trim()
  return name || description || ''
}

/**
 * Prefer spawn prompt when the controller label is just an id.
 * Falls back to label, then a short result preview.
 */
export function resolveSubtaskTitle(
  subtask: Pick<WorkflowSubtask, 'label' | 'resultPreview' | 'error'>,
  spawnPrompt?: string | null,
  maxChars = 72
): string {
  const prompt = (spawnPrompt || '').replace(/\s+/g, ' ').trim()
  if (prompt && isOpaqueSubtaskLabel(subtask.label)) {
    return clipWorkflowText(prompt, maxChars)
  }
  if (!isOpaqueSubtaskLabel(subtask.label)) {
    return clipWorkflowText(subtask.label, maxChars)
  }
  if (prompt) return clipWorkflowText(prompt, maxChars)
  const err = subtask.error?.replace(/\s+/g, ' ').trim()
  if (err) return clipWorkflowText(err, maxChars)
  const preview = subtask.resultPreview?.replace(/\s+/g, ' ').trim()
  if (preview) return clipWorkflowText(preview, maxChars)
  return clipWorkflowText(subtask.label, maxChars)
}

function statusRank(status: WorkflowSubtaskStatus): number {
  switch (status) {
    case 'running':
      return 0
    case 'error':
      return 1
    case 'queued':
      return 2
    case 'done':
      return 3
    case 'skipped':
      return 4
    default:
      return 5
  }
}

/**
 * Real work units from controller spawns.
 * Drops shell parents (no agent_id) and orchestrate/dynamic chrome labels.
 */
export function workflowSubtasks(snapshot: WorkflowSnapshotPayload): WorkflowSubtask[] {
  const out: WorkflowSubtask[] = []
  const seen = new Set<string>()
  for (const agent of snapshot.agents) {
    const agentId = agent.agent_id?.trim()
    if (!agentId) continue
    if (isWorkflowShellLabel(agent.label) && !agent.result_preview && !agent.error) continue
    if (seen.has(agentId)) continue
    seen.add(agentId)
    const label = agent.label.trim() || agentId
    // Keep opaque labels — title resolution uses spawn prompt at render time.
    out.push({
      agentId,
      label,
      status: agent.status,
      stepId: agent.step_id,
      resultPreview: agent.result_preview ?? null,
      error: agent.error ?? null
    })
  }
  out.sort((a, b) => {
    const rank = statusRank(a.status) - statusRank(b.status)
    if (rank !== 0) return rank
    return a.label.localeCompare(b.label)
  })
  return out
}

export function workflowFocusSubtask(subtasks: WorkflowSubtask[]): WorkflowSubtask | null {
  return (
    subtasks.find((s) => s.status === 'running') ??
    subtasks.find((s) => s.status === 'error') ??
    subtasks.find((s) => s.status === 'queued') ??
    null
  )
}

export function workflowSubtaskProgress(subtasks: WorkflowSubtask[]): {
  done: number
  total: number
} {
  const total = subtasks.length
  const done = subtasks.filter((s) => s.status === 'done' || s.status === 'skipped').length
  return { done, total }
}
