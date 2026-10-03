// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it, vi } from 'vitest'
import { useLiveTasks, useThreadsWithActiveTasks } from './use-thread-tasks'
import type { TaskItemView } from '../lib/extract-tasks-from-blocks'
it('keeps a task older than 100 newer tasks in the index and live status overlay', async () => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true
  const tasks = [...Array.from({ length: 100 }, (_, i) => ({ id: `new-${i}`, status: 'completed' })),
    { id: 'old', thread_id: 'old-thread', status: 'running' }]
  const request = vi.fn(async (path: string) => ({ ok: true, body: JSON.stringify({ tasks: path.includes('limit=100') ? tasks.slice(0, 100) : tasks }) }))
  vi.stubGlobal('dsGui', { runtimeRequest: request })
  const host = document.createElement('div'); document.body.append(host)
  const root = createRoot(host)
  function Probe() {
    const index = useThreadsWithActiveTasks()
    const live = useLiveTasks([{ id: 'old', status: 'queued' } as TaskItemView])
    return createElement('p', null, `${index.threadIds.has('old-thread')}:${live[0].status}`)
  }
  try {
    await act(async () => root.render(createElement(Probe)))
    expect(host.textContent).toBe('true:running')
    expect(request).toHaveBeenCalledWith('/v1/tasks?active_only=true', 'GET')
    expect(request).toHaveBeenCalledWith('/v1/tasks?ids=old', 'GET')
  } finally { await act(async () => root.unmount()); host.remove(); vi.unstubAllGlobals() }
})
