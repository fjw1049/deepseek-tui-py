import { useEffect, useState } from 'react'

export type CuaTask = {
  key: string
  thread_id: string | null
  app: string | null
  app_name?: string
  surface?: { kind: string; app_id?: string }
  waiting: boolean
  external?: boolean
  revision?: number
  can_stop: boolean
}

/** Tickets are shared by local runtimes, including independent evaluation processes. */
export function useCuaTasks(): CuaTask[] {
  const [tasks, setTasks] = useState<CuaTask[]>([])
  useEffect(() => {
    if (!window.dsGui?.runtimeRequest) return
    let disposed = false
    let timer: ReturnType<typeof setTimeout>
    const poll = async (): Promise<void> => {
      let active = false
      try {
        const response = await window.dsGui.runtimeRequest('/v1/cua/tasks', 'GET')
        const next = response.ok ? JSON.parse(response.body).tasks : []
        if (!disposed && Array.isArray(next)) {
          active = next.length > 0
          setTasks(old => JSON.stringify(old) === JSON.stringify(next) ? old : next)
        }
      } catch { if (!disposed) setTasks([]) }
      if (!disposed) timer = setTimeout(() => void poll(), active ? 600 : 1800)
    }
    void poll()
    return () => { disposed = true; clearTimeout(timer) }
  }, [])
  return tasks
}
