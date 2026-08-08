import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  createAutomation,
  formatAutomationApiError,
  listAutomations,
  listAutomationRuns,
  updateAutomation
} from './automation-runtime-client'

describe('automation-runtime-client', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('extracts message from FastAPI detail objects', () => {
    expect(
      formatAutomationApiError(
        JSON.stringify({
          detail: {
            message: 'automation manager not configured',
            error: 'runtime_error'
          }
        }),
        'HTTP 503'
      )
    ).toBe('automation manager not configured')
  })

  it('extracts string detail and validation msg arrays', () => {
    expect(formatAutomationApiError(JSON.stringify({ detail: 'bad request' }), 'HTTP 400')).toBe(
      'bad request'
    )
    expect(
      formatAutomationApiError(
        JSON.stringify({
          detail: [{ loc: ['body', 'name'], msg: 'Field required', type: 'missing' }]
        }),
        'HTTP 422'
      )
    ).toBe('Field required')
  })

  it('surfaces detail.message when listAutomations fails', async () => {
    const runtimeRequest = vi.fn().mockResolvedValue({
      ok: false,
      status: 503,
      body: JSON.stringify({
        detail: {
          message: 'automation manager not configured',
          error: 'runtime_error'
        }
      })
    })
    vi.stubGlobal('window', { dsGui: { runtimeRequest } })

    await expect(listAutomations()).rejects.toThrow('automation manager not configured')
  })

  it('posts create automation payloads to the runtime API', async () => {
    const runtimeRequest = vi.fn().mockResolvedValue({
      ok: true,
      status: 201,
      body: JSON.stringify({
        id: 'auto_1',
        name: 'Daily report',
        prompt: 'Summarize changes',
        schedule: '0 * * * *',
        timezone: 'Asia/Shanghai',
        status: 'active'
      })
    })
    vi.stubGlobal('window', { dsGui: { runtimeRequest } })

    const record = await createAutomation({
      name: 'Daily report',
      prompt: 'Summarize changes',
      schedule: '0 * * * *',
      status: 'active',
      cwds: ['/tmp/project']
    })

    expect(runtimeRequest).toHaveBeenCalledWith(
      '/v1/automations',
      'POST',
      JSON.stringify({
        name: 'Daily report',
        prompt: 'Summarize changes',
        schedule: '0 * * * *',
        status: 'active',
        cwds: ['/tmp/project']
      })
    )
    expect(record.id).toBe('auto_1')
  })

  it('patches automation payloads', async () => {
    const runtimeRequest = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      body: JSON.stringify({ id: 'auto_1', name: 'Renamed', prompt: 'Run', schedule: '0 * * * *', timezone: 'Asia/Shanghai', status: 'active' })
    })
    vi.stubGlobal('window', { dsGui: { runtimeRequest } })

    await updateAutomation('auto_1', { name: 'Renamed' })

    expect(runtimeRequest).toHaveBeenCalledWith(
      '/v1/automations/auto_1',
      'PATCH',
      JSON.stringify({ name: 'Renamed' })
    )
  })

  it('loads run history with a bounded limit', async () => {
    const runtimeRequest = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      body: JSON.stringify([{ id: 'run_1', automation_id: 'auto_1', scheduled_for: '2026-06-07T00:00:00Z', status: 'succeeded', created_at: '2026-06-07T00:00:00Z' }])
    })
    vi.stubGlobal('window', { dsGui: { runtimeRequest } })

    const runs = await listAutomationRuns('auto_1', 20)

    expect(runtimeRequest).toHaveBeenCalledWith('/v1/automations/auto_1/runs?limit=20', 'GET', undefined)
    expect(runs[0]?.id).toBe('run_1')
  })
})
