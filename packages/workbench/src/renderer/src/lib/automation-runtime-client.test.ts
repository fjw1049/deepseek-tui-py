import { afterEach, describe, expect, it, vi } from 'vitest'
import { createAutomation } from './automation-runtime-client'

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
})
