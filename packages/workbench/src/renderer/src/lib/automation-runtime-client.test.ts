import { afterEach, describe, expect, it, vi } from 'vitest'
import { createAutomation, listAutomationRuns, updateAutomation } from './automation-runtime-client'

describe('automation-runtime-client', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('posts create automation payloads to the runtime API', async () => {
    const runtimeRequest = vi.fn().mockResolvedValue({
      ok: true,
      status: 201,
      body: JSON.stringify({
        id: 'auto_1',
        name: 'Daily report',
        prompt: 'Summarize changes',
        rrule: 'FREQ=HOURLY;INTERVAL=1',
        status: 'active'
      })
    })
    vi.stubGlobal('window', { dsGui: { runtimeRequest } })

    const record = await createAutomation({
      name: 'Daily report',
      prompt: 'Summarize changes',
      rrule: 'FREQ=HOURLY;INTERVAL=1',
      status: 'active',
      cwds: ['/tmp/project']
    })

    expect(runtimeRequest).toHaveBeenCalledWith(
      '/v1/automations',
      'POST',
      JSON.stringify({
        name: 'Daily report',
        prompt: 'Summarize changes',
        rrule: 'FREQ=HOURLY;INTERVAL=1',
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
      body: JSON.stringify({ id: 'auto_1', name: 'Renamed', prompt: 'Run', rrule: 'FREQ=HOURLY', status: 'active' })
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
