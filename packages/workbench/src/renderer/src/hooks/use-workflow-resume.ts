/** Direct workflow resume (POST /v1/workflow/{run_id}/resume). */

export type WorkflowResumeResult = {
  runId: string
  taskId: string
}

export async function resumeWorkflow(
  runId: string,
  threadId?: string
): Promise<WorkflowResumeResult> {
  if (typeof window.dsGui?.runtimeRequest !== 'function') {
    throw new Error('runtime unavailable')
  }
  const r = await window.dsGui.runtimeRequest(
    `/v1/workflow/${encodeURIComponent(runId)}/resume`,
    'POST',
    JSON.stringify(threadId ? { detach: true, thread_id: threadId } : { detach: true })
  )
  if (!r.ok) {
    throw new Error(r.body?.trim() || `resume workflow failed (${r.status})`)
  }
  let raw: Record<string, unknown>
  try {
    raw = JSON.parse(r.body) as Record<string, unknown>
  } catch {
    throw new Error('resume workflow returned invalid JSON')
  }
  if (raw.ok === false) {
    throw new Error(
      typeof raw.error === 'string' && raw.error.trim()
        ? raw.error
        : 'resume workflow failed'
    )
  }
  const run =
    typeof raw.run_id === 'string'
      ? raw.run_id
      : typeof raw.runId === 'string'
        ? raw.runId
        : runId
  const task =
    typeof raw.task_id === 'string'
      ? raw.task_id
      : typeof raw.taskId === 'string'
        ? raw.taskId
        : ''
  if (!task) {
    throw new Error('resume workflow missing task_id')
  }
  return { runId: run, taskId: task }
}
