import { useEffect, useState } from 'react'
import { fetchTaskDetail, type TaskDetail } from './use-thread-tasks'
import { isActiveTaskStatus } from '../lib/extract-tasks-from-blocks'

/** Only the visible task polls. Requests never overlap or replace another task's data. */
export function useTaskRunDetail(taskId: string | null, refresh: number): {
  detail: TaskDetail | null
  loading: boolean
  failed: boolean
} {
  const [state, setState] = useState({
    id: taskId, detail: null as TaskDetail | null, loading: true, failed: false
  })
  useEffect(() => {
    if (!taskId) return
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const load = async (): Promise<void> => {
      let active = true
      try {
        const detail = await fetchTaskDetail(taskId)
        if (cancelled) return
        setState({ id: taskId, detail, loading: false, failed: !detail })
        active = !detail || isActiveTaskStatus(detail.status)
      } catch {
        if (cancelled) return
        setState((prev) => ({ ...prev, id: taskId, loading: false, failed: true }))
      }
      if (!cancelled && active) timer = setTimeout(() => void load(), 1500)
    }
    void load()
    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
  }, [taskId, refresh])
  return state.id === taskId ? state : { detail: null, loading: true, failed: false }
}
