import { afterEach, describe, expect, it, vi } from 'vitest'
import { requestTaskResume } from './resume-task'

const review = {
  ok: false,
  code: 'resume_confirmation_required',
  permission_changes: [{ field: 'auto_approve', current: false, target: true }],
  resume_permissions: { workspace: '/original/project' },
  confirmation_key: 'reviewed-scope'
}
const response = (body: unknown) => ({ ok: true, status: 200, body: JSON.stringify(body) })

afterEach(() => vi.unstubAllGlobals())

describe('task permission review', () => {
  it('shows concrete changes and resubmits only after user confirmation', async () => {
    const runtimeRequest = vi.fn().mockResolvedValueOnce(response(review))
      .mockResolvedValueOnce(response({ id: 'task_1', status: 'queued' }))
    const confirm = vi.fn().mockReturnValue(true)
    vi.stubGlobal('window', { dsGui: { runtimeRequest }, confirm })
    expect(await requestTaskResume('task_1', 'current_thread')).toMatchObject({ status: 'queued' })
    expect(confirm.mock.calls[0][0]).toContain('/original/project')
    expect(confirm.mock.calls[0][0]).toContain('→')
    expect(JSON.parse(runtimeRequest.mock.calls[0][2])).toEqual({ thread_id: 'current_thread' })
    expect(JSON.parse(runtimeRequest.mock.calls[1][2])).toEqual({
      thread_id: 'current_thread', confirmation_key: 'reviewed-scope'
    })
  })

  it('does not enqueue when the user declines', async () => {
    const runtimeRequest = vi.fn().mockResolvedValue(response(review))
    vi.stubGlobal('window', { dsGui: { runtimeRequest }, confirm: () => false })
    await expect(requestTaskResume('task_1')).rejects.toThrow()
    expect(runtimeRequest).toHaveBeenCalledTimes(1)
  })

  it('requires a fresh review if the scope changed during confirmation', async () => {
    const runtimeRequest = vi.fn().mockResolvedValue(response(review))
    const confirm = vi.fn().mockReturnValue(true)
    vi.stubGlobal('window', { dsGui: { runtimeRequest }, confirm })
    await expect(requestTaskResume('task_1')).rejects.toThrow()
    expect(runtimeRequest).toHaveBeenCalledTimes(2)
    expect(confirm).toHaveBeenCalledTimes(1)
  })
})
