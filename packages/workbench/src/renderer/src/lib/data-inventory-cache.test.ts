// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest'
import { getDataInventorySnapshot, loadDataInventory } from './data-inventory-cache'

const response = (bytes: number) => ({ ok: true, body: JSON.stringify({ total_bytes: bytes }) })
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

describe('data inventory cache', () => {
  it('shares in-flight requests and reuses a recent scan across visits', async () => {
    const request = vi.fn(async () => response(100))
    vi.stubGlobal('dsGui', { runtimeRequest: request })
    expect(getDataInventorySnapshot()).toBeNull()
    const first = loadDataInventory()
    expect(loadDataInventory()).toBe(first)
    await first
    expect(getDataInventorySnapshot()?.total_bytes).toBe(100)
    await loadDataInventory()
    expect(request).toHaveBeenCalledOnce()
  })

  it('keeps the previous snapshot during a stale refresh and after a failure', async () => {
    const request = vi.fn(async () => response(100))
    vi.stubGlobal('dsGui', { runtimeRequest: request })
    const now = Date.now()
    vi.spyOn(Date, 'now').mockReturnValue(now)
    await loadDataInventory()
    vi.mocked(Date.now).mockReturnValue(now + 30_001)
    request.mockRejectedValueOnce(new Error('Offline'))
    await expect(loadDataInventory()).rejects.toThrow('Offline')
    expect(getDataInventorySnapshot()?.total_bytes).toBe(100)
    request.mockResolvedValueOnce(response(200))
    await loadDataInventory()
    expect(getDataInventorySnapshot()?.total_bytes).toBe(200)
    expect(request).toHaveBeenCalledTimes(3)
  })

  it('starts a new scan after an in-flight scan when a mutation forces refresh', async () => {
    let finish!: (value: ReturnType<typeof response>) => void
    const request = vi.fn(() => new Promise<ReturnType<typeof response>>(resolve => { finish = resolve }))
    vi.stubGlobal('dsGui', { runtimeRequest: request })
    const stale = loadDataInventory()
    const fresh = loadDataInventory(true)
    request.mockResolvedValueOnce(response(200))
    finish(response(100))
    await stale
    expect((await fresh).total_bytes).toBe(200)
    expect(request).toHaveBeenCalledTimes(2)
  })

  it('does not reuse snapshots from a different runtime bridge', async () => {
    vi.stubGlobal('dsGui', { runtimeRequest: vi.fn(async () => response(100)) })
    await loadDataInventory()
    vi.stubGlobal('dsGui', { runtimeRequest: vi.fn(async () => response(200)) })
    expect(getDataInventorySnapshot()).toBeNull()
    expect((await loadDataInventory()).total_bytes).toBe(200)
  })
})
