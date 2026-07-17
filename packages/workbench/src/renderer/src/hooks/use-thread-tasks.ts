import { useEffect, useState } from 'react'
import {
  isActiveTaskStatus,
  normalizeTaskStatus,
  type TaskItemView,
  type TaskStatus
} from '../lib/extract-tasks-from-blocks'

const POLL_INTERVAL_MS = 2_000

export type TaskTimelineEntry = {
  timestamp: string | null
  kind: string
  summary: string
  detail?: string | null
}

export type TaskDetail = {
  id: string
  status: TaskStatus
  prompt: string
  resultSummary: string | null
  error: string | null
  durationMs: number | null
  timeline: TaskTimelineEntry[]
}

function parseTimeline(raw: unknown): TaskTimelineEntry[] {
  if (!Array.isArray(raw)) return []
  const out: TaskTimelineEntry[] = []
  for (const entry of raw) {
    if (!entry || typeof entry !== 'object') continue
    const row = entry as Record<string, unknown>
    const kind = typeof row.kind === 'string' ? row.kind : ''
    const summary = typeof row.summary === 'string' ? row.summary : ''
    if (!kind && !summary) continue
    out.push({
      timestamp: typeof row.timestamp === 'string' ? row.timestamp : null,
      kind,
      summary,
      detail: typeof row.detail === 'string' ? row.detail : null
    })
  }
  return out
}

/**
 * Fetch the full record for a single durable task. The list endpoint only
 * carries id/status; this hits `GET /v1/tasks/{id}` for the prompt, result
 * summary and timing so the dock can reveal them on demand.
 */
export async function fetchTaskDetail(id: string): Promise<TaskDetail | null> {
  if (typeof window.dsGui?.runtimeRequest !== 'function') return null
  const r = await window.dsGui.runtimeRequest(`/v1/tasks/${encodeURIComponent(id)}`, 'GET')
  if (!r.ok || !r.body.trim()) return null
  let raw: Record<string, unknown>
  try {
    raw = JSON.parse(r.body) as Record<string, unknown>
  } catch {
    return null
  }
  // Some routes return the record directly, others wrap it as `{ ok, task }`.
  const t =
    raw.task && typeof raw.task === 'object' ? (raw.task as Record<string, unknown>) : raw
  return {
    id: typeof t.id === 'string' ? t.id : id,
    status: normalizeTaskStatus(t.status),
    prompt: typeof t.prompt === 'string' ? t.prompt : '',
    resultSummary: typeof t.result_summary === 'string' ? t.result_summary : null,
    error: typeof t.error === 'string' ? t.error : null,
    durationMs: typeof t.duration_ms === 'number' ? t.duration_ms : null,
    timeline: parseTimeline(t.timeline)
  }
}

export type ActiveTaskIndex = {
  /** Thread ids that own a queued/running task (via the task's `thread_id`). */
  threadIds: Set<string>
  /** Ids of every queued/running task, regardless of thread attribution. */
  taskIds: Set<string>
}

const EMPTY_ACTIVE_TASK_INDEX: ActiveTaskIndex = { threadIds: new Set(), taskIds: new Set() }

async function fetchActiveTaskIndex(): Promise<ActiveTaskIndex> {
  if (typeof window.dsGui?.runtimeRequest !== 'function') return EMPTY_ACTIVE_TASK_INDEX
  const r = await window.dsGui.runtimeRequest('/v1/tasks?limit=100', 'GET')
  if (!r.ok || !r.body.trim()) return EMPTY_ACTIVE_TASK_INDEX
  let parsed: { tasks?: Array<Record<string, unknown>> }
  try {
    parsed = JSON.parse(r.body) as { tasks?: Array<Record<string, unknown>> }
  } catch {
    return EMPTY_ACTIVE_TASK_INDEX
  }
  const threadIds = new Set<string>()
  const taskIds = new Set<string>()
  for (const task of parsed.tasks ?? []) {
    if (!isActiveTaskStatus(normalizeTaskStatus(task.status))) continue
    const id = typeof task.id === 'string' ? task.id : ''
    if (id) taskIds.add(id)
    const threadId = typeof task.thread_id === 'string' ? task.thread_id : ''
    if (threadId) threadIds.add(threadId)
  }
  return { threadIds, taskIds }
}

const ACTIVE_THREADS_POLL_MS = 3_000

function sameSet(a: Set<string>, b: Set<string>): boolean {
  if (a.size !== b.size) return false
  for (const v of a) if (!b.has(v)) return false
  return true
}

/**
 * Poll `GET /v1/tasks` for the set of conversations with background work in
 * flight. `threadIds` attributes active tasks by their stored `thread_id`
 * (covers any conversation, but only for tasks created after the thread_id
 * wiring landed). `taskIds` lets a caller that already knows a conversation's
 * task ids (e.g. from its message blocks) light it up without relying on
 * thread attribution.
 */
export function useThreadsWithActiveTasks(): ActiveTaskIndex {
  const [index, setIndex] = useState<ActiveTaskIndex>(() => EMPTY_ACTIVE_TASK_INDEX)

  useEffect(() => {
    let cancelled = false
    const refresh = (): void => {
      void fetchActiveTaskIndex().then((next) => {
        if (cancelled) return
        setIndex((prev) =>
          sameSet(prev.threadIds, next.threadIds) && sameSet(prev.taskIds, next.taskIds)
            ? prev
            : next
        )
      })
    }
    refresh()
    const interval = window.setInterval(refresh, ACTIVE_THREADS_POLL_MS)
    return () => {
      cancelled = true
      window.clearInterval(interval)
    }
  }, [])

  return index
}

async function fetchTaskStatuses(): Promise<Record<string, TaskStatus>> {
  if (typeof window.dsGui?.runtimeRequest !== 'function') return {}
  const r = await window.dsGui.runtimeRequest('/v1/tasks?limit=100', 'GET')
  if (!r.ok || !r.body.trim()) return {}
  let parsed: { tasks?: Array<Record<string, unknown>> }
  try {
    parsed = JSON.parse(r.body) as { tasks?: Array<Record<string, unknown>> }
  } catch {
    return {}
  }
  const out: Record<string, TaskStatus> = {}
  for (const task of parsed.tasks ?? []) {
    const id = typeof task.id === 'string' ? task.id : ''
    if (!id) continue
    out[id] = normalizeTaskStatus(task.status)
  }
  return out
}

/**
 * Overlay live durable-task status onto conversation-derived tasks.
 *
 * Durable tasks run in a background worker that never emits events on the
 * thread SSE stream, so a `task_create` tool block is frozen at `queued`.
 * This polls `GET /v1/tasks` to refresh status, but only while at least one
 * of the given tasks is still active (queued/running) — once everything is
 * terminal, polling stops.
 */
export function useLiveTasks(baseTasks: TaskItemView[]): TaskItemView[] {
  const [liveStatuses, setLiveStatuses] = useState<Record<string, TaskStatus>>({})

  const idsKey = baseTasks.map((task) => task.id).join(',')
  const anyActive = baseTasks.some((task) =>
    isActiveTaskStatus(liveStatuses[task.id] ?? task.status)
  )

  useEffect(() => {
    const ids = idsKey ? idsKey.split(',') : []
    if (ids.length === 0) {
      setLiveStatuses((prev) => (Object.keys(prev).length === 0 ? prev : {}))
      return
    }
    let cancelled = false
    const refresh = (): void => {
      void fetchTaskStatuses().then((all) => {
        if (cancelled) return
        const next: Record<string, TaskStatus> = {}
        for (const id of ids) {
          if (all[id]) next[id] = all[id]
        }
        setLiveStatuses((prev) => {
          const sameSize = Object.keys(prev).length === Object.keys(next).length
          if (sameSize && ids.every((id) => prev[id] === next[id])) return prev
          return next
        })
      })
    }
    refresh()
    const interval = anyActive ? window.setInterval(refresh, POLL_INTERVAL_MS) : undefined
    return () => {
      cancelled = true
      if (interval !== undefined) window.clearInterval(interval)
    }
  }, [idsKey, anyActive])

  return baseTasks.map((task) => {
    const live = liveStatuses[task.id]
    return live ? { ...task, status: live } : task
  })
}
