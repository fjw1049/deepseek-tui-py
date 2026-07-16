export type WorkflowAgentRun = {
  step_id: string
  label: string
  phase_id: string
  status: 'queued' | 'running' | 'done' | 'error' | 'skipped'
  agent_id?: string | null
  result_preview?: string | null
  error?: string | null
}

export type WorkflowNodeSnapshot = {
  id: string
  type: string
  status: 'queued' | 'running' | 'done' | 'error' | 'skipped'
  generated?: boolean
  predecessors?: string[]
  label?: string | null
}

export type WorkflowSnapshotPayload = {
  name: string
  description: string
  phases: string[]
  current_phase?: string | null
  logs: string[]
  agents: WorkflowAgentRun[]
  agent_count: number
  running_count: number
  done_count: number
  error_count: number
  duration_ms?: number | null
  result?: unknown
  nodes?: WorkflowNodeSnapshot[]
  edges?: Array<{ from: string; to: string }>
  dynamic_rounds?: Record<string, number>
}

export type WorkflowProgressPayload = {
  toolCallId: string
  workflowName: string
  snapshot: WorkflowSnapshotPayload
  completed: boolean
  status?: 'running' | 'completed' | 'failed' | 'cancelled' | 'timed_out'
  runId?: string
}

function asAgentRun(raw: unknown): WorkflowAgentRun | null {
  if (!raw || typeof raw !== 'object') return null
  const a = raw as Record<string, unknown>
  const stepId = typeof a.step_id === 'string' ? a.step_id : ''
  const label = typeof a.label === 'string' ? a.label : stepId
  const phaseId = typeof a.phase_id === 'string' ? a.phase_id : ''
  const status = a.status
  if (
    status !== 'queued' &&
    status !== 'running' &&
    status !== 'done' &&
    status !== 'error' &&
    status !== 'skipped'
  ) {
    return null
  }
  return {
    step_id: stepId,
    label,
    phase_id: phaseId,
    status,
    agent_id: typeof a.agent_id === 'string' ? a.agent_id : null,
    result_preview: typeof a.result_preview === 'string' ? a.result_preview : null,
    error: typeof a.error === 'string' ? a.error : null
  }
}

function asNodeSnapshot(raw: unknown): WorkflowNodeSnapshot | null {
  if (!raw || typeof raw !== 'object') return null
  const n = raw as Record<string, unknown>
  const id = typeof n.id === 'string' ? n.id : ''
  const type = typeof n.type === 'string' ? n.type : ''
  const status = n.status
  if (
    !id ||
    (status !== 'queued' &&
      status !== 'running' &&
      status !== 'done' &&
      status !== 'error' &&
      status !== 'skipped')
  ) {
    return null
  }
  return {
    id,
    type: type || 'agent',
    status,
    generated: n.generated === true,
    predecessors: Array.isArray(n.predecessors)
      ? n.predecessors.filter((p): p is string => typeof p === 'string')
      : [],
    label: typeof n.label === 'string' ? n.label : null
  }
}

export function parseWorkflowSnapshot(raw: unknown): WorkflowSnapshotPayload | null {
  if (!raw || typeof raw !== 'object') return null
  const s = raw as Record<string, unknown>
  const name = typeof s.name === 'string' ? s.name : ''
  const description = typeof s.description === 'string' ? s.description : ''
  if (!name) return null
  const phases = Array.isArray(s.phases)
    ? s.phases.filter((p): p is string => typeof p === 'string')
    : []
  const agents = Array.isArray(s.agents)
    ? s.agents.map(asAgentRun).filter((a): a is WorkflowAgentRun => a != null)
    : []
  const nodes = Array.isArray(s.nodes)
    ? s.nodes.map(asNodeSnapshot).filter((n): n is WorkflowNodeSnapshot => n != null)
    : undefined
  const edges = Array.isArray(s.edges)
    ? s.edges
        .map((e) => {
          if (!e || typeof e !== 'object') return null
          const row = e as Record<string, unknown>
          const from = typeof row.from === 'string' ? row.from : ''
          const to = typeof row.to === 'string' ? row.to : ''
          return from && to ? { from, to } : null
        })
        .filter((e): e is { from: string; to: string } => e != null)
    : undefined
  const dynamicRounds =
    s.dynamic_rounds && typeof s.dynamic_rounds === 'object'
      ? Object.fromEntries(
          Object.entries(s.dynamic_rounds as Record<string, unknown>).filter(
            (entry): entry is [string, number] => typeof entry[1] === 'number'
          )
        )
      : undefined
  return {
    name,
    description,
    phases,
    current_phase: typeof s.current_phase === 'string' ? s.current_phase : null,
    logs: Array.isArray(s.logs) ? s.logs.filter((l): l is string => typeof l === 'string') : [],
    agents,
    agent_count: typeof s.agent_count === 'number' ? s.agent_count : agents.length,
    running_count: typeof s.running_count === 'number' ? s.running_count : 0,
    done_count: typeof s.done_count === 'number' ? s.done_count : 0,
    error_count: typeof s.error_count === 'number' ? s.error_count : 0,
    duration_ms: typeof s.duration_ms === 'number' ? s.duration_ms : null,
    result: s.result,
    nodes,
    edges,
    dynamic_rounds: dynamicRounds
  }
}

export function parseWorkflowProgressPayload(
  payload: Record<string, unknown>
): WorkflowProgressPayload | null {
  const toolCallId =
    typeof payload.tool_call_id === 'string'
      ? payload.tool_call_id
      : typeof payload.toolCallId === 'string'
        ? payload.toolCallId
        : ''
  const workflowName =
    typeof payload.workflow_name === 'string'
      ? payload.workflow_name
      : typeof payload.workflowName === 'string'
        ? payload.workflowName
        : ''
  const snapshot = parseWorkflowSnapshot(payload.snapshot)
  if (!toolCallId || !snapshot) return null
  return {
    toolCallId,
    workflowName: workflowName || snapshot.name,
    snapshot,
    completed: payload.completed === true,
    status:
      payload.status === 'running' ||
      payload.status === 'completed' ||
      payload.status === 'failed' ||
      payload.status === 'cancelled' ||
      payload.status === 'timed_out'
        ? payload.status
        : undefined,
    runId:
      typeof payload.run_id === 'string'
        ? payload.run_id
        : typeof payload.runId === 'string'
          ? payload.runId
          : undefined
  }
}

export function workflowSnapshotFromToolMeta(
  meta: Record<string, unknown> | undefined
): WorkflowSnapshotPayload | null {
  if (!meta) return null
  const workflow = meta.workflow
  if (!workflow || typeof workflow !== 'object') return null
  const w = workflow as Record<string, unknown>
  return parseWorkflowSnapshot(w.snapshot)
}

export function workflowRunIdFromToolMeta(
  meta: Record<string, unknown> | undefined
): string | undefined {
  if (!meta) return undefined
  const workflow = meta.workflow
  if (!workflow || typeof workflow !== 'object') return undefined
  const w = workflow as Record<string, unknown>
  return typeof w.run_id === 'string' && w.run_id.trim() ? w.run_id.trim() : undefined
}
