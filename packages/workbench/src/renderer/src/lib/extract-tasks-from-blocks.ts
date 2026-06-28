import type { ChatBlock } from '../agent/types'

export type TaskStatus = 'queued' | 'running' | 'completed' | 'failed' | 'canceled'

export type TaskItemView = {
  id: string
  status: TaskStatus
  prompt: string
}

// Only tools that reference a single, conversation-scoped task define
// membership. `task_list` is intentionally excluded: it returns the
// process-global task history (often dozens of stale records), which would
// flood the panel with tasks this conversation never created.
const TASK_TOOL_NAMES = new Set(['task_create', 'task_read', 'task_cancel'])

export const TERMINAL_TASK_STATUSES: ReadonlySet<TaskStatus> = new Set<TaskStatus>([
  'completed',
  'failed',
  'canceled'
])

export function isActiveTaskStatus(status: TaskStatus): boolean {
  return !TERMINAL_TASK_STATUSES.has(status)
}

export function normalizeTaskStatus(raw: unknown): TaskStatus {
  if (typeof raw !== 'string') return 'queued'
  let s = raw.trim().toLowerCase()
  const dot = s.lastIndexOf('.')
  if (dot >= 0) s = s.slice(dot + 1)
  if (s === 'running') return 'running'
  if (s === 'completed' || s === 'done') return 'completed'
  if (s === 'failed' || s === 'error') return 'failed'
  if (s === 'canceled' || s === 'cancelled') return 'canceled'
  return 'queued'
}

function toolNameFromBlock(block: Extract<ChatBlock, { kind: 'tool' }>): string | undefined {
  const metaName = typeof block.meta?.tool_name === 'string' ? block.meta.tool_name : undefined
  if (metaName) return metaName
  const head = block.summary.trim().split(/[:(]/, 1)[0]?.trim()
  return head || undefined
}

function isTaskToolBlock(block: ChatBlock): block is Extract<ChatBlock, { kind: 'tool' }> {
  if (block.kind !== 'tool') return false
  const name = toolNameFromBlock(block)
  return name ? TASK_TOOL_NAMES.has(name) : false
}

function parseTasksFromBlock(block: Extract<ChatBlock, { kind: 'tool' }>): TaskItemView[] | null {
  const raw = block.meta?.tasks
  if (!Array.isArray(raw) || raw.length === 0) return null
  const tasks: TaskItemView[] = []
  for (const entry of raw) {
    if (!entry || typeof entry !== 'object') continue
    const row = entry as Record<string, unknown>
    const id = typeof row.id === 'string' ? row.id.trim() : ''
    if (!id) continue
    const prompt = typeof row.prompt === 'string' ? row.prompt.trim() : ''
    tasks.push({ id, status: normalizeTaskStatus(row.status), prompt })
  }
  return tasks.length > 0 ? tasks : null
}

/**
 * Collect the latest known state of every durable task referenced by the
 * thread's task tool calls. Later blocks override earlier ones by task id, so
 * a task's status reflects the most recent `task_*` call that touched it.
 */
export function extractTasksFromBlocks(blocks: ChatBlock[]): TaskItemView[] {
  const byId = new Map<string, TaskItemView>()
  for (const block of blocks) {
    if (!isTaskToolBlock(block)) continue
    if (block.status === 'error') continue
    const parsed = parseTasksFromBlock(block)
    if (!parsed) continue
    for (const task of parsed) byId.set(task.id, task)
  }
  return [...byId.values()]
}
