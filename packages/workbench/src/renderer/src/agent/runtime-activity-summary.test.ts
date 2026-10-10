// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from 'vitest'
import { DeepseekRuntimeProvider } from './deepseek-runtime'

afterEach(() => vi.unstubAllGlobals())

it('loads all projects without a recent-50 limit and preserves activity summaries', async () => {
  const runtimeRequest = vi.fn(async () => ({ ok: true, body: JSON.stringify([{
    id: 'older-failed', title: 'Older failure', updated_at: '2026-09-01', model: 'deepseek', mode: 'agent',
    latest_turn_status: 'failed', latest_turn_failed: true, activity_waiting: true, activity_at: '2026-09-01'
  }]) }))
  vi.stubGlobal('dsGui', { runtimeRequest })
  const threads = await new DeepseekRuntimeProvider().listThreads()
  expect(runtimeRequest).toHaveBeenCalledWith('/v1/threads', 'GET')
  expect(threads[0]).toMatchObject({ latestTurnStatus: 'failed', latestTurnFailed: true, activityWaiting: true, activityAt: '2026-09-01' })
})
