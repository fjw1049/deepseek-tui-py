import { afterEach, describe, expect, it, vi } from 'vitest'
import { resumeTask, resumeThreadAgent } from './use-thread-tasks'

describe('direct resume helpers', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('posts task resume without a main-turn prompt', async () => {
    const runtimeRequest = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      body: JSON.stringify({
        id: 'task_1',
        status: 'queued',
        prompt: 'continue work',
        timeline: []
      })
    })
    vi.stubGlobal('window', { dsGui: { runtimeRequest } })

    const detail = await resumeTask('task_1')

    expect(runtimeRequest).toHaveBeenCalledWith('/v1/tasks/task_1/resume', 'POST')
    expect(detail.id).toBe('task_1')
    expect(detail.status).toBe('queued')
  })

  it('posts thread agent resume', async () => {
    const runtimeRequest = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      body: JSON.stringify({
        agent_id: 'agent_abc',
        status: { kind: 'running' }
      })
    })
    vi.stubGlobal('window', { dsGui: { runtimeRequest } })

    await resumeThreadAgent('thread_1', 'agent_abc')

    expect(runtimeRequest).toHaveBeenCalledWith(
      '/v1/threads/thread_1/agents/agent_abc/resume',
      'POST'
    )
  })

  it('surfaces HTTP errors from agent resume', async () => {
    const runtimeRequest = vi.fn().mockResolvedValue({
      ok: false,
      status: 409,
      body: JSON.stringify({ detail: { message: 'already running' } })
    })
    vi.stubGlobal('window', { dsGui: { runtimeRequest } })

    await expect(resumeThreadAgent('thread_1', 'agent_abc')).rejects.toThrow(
      /already running|409/
    )
  })
})
