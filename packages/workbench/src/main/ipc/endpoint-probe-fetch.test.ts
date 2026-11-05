import { expect, it, vi } from 'vitest'
import { fetchEndpointProbe } from './endpoint-probe-fetch'

it.each([200, 400, 401, 403, 429])('does not retry HTTP %s', async (status) => {
  const response = new Response('', { status })
  const system = vi.fn<typeof fetch>().mockResolvedValue(response)
  const direct = vi.fn<typeof fetch>()
  expect(await fetchEndpointProbe('https://example.test', {}, system, direct)).toBe(response)
  expect(direct).not.toHaveBeenCalled()
})

it.each([502, 503, 504, 'network'])('falls back for %s without changing the request', async (failure) => {
  const system = vi.fn<typeof fetch>()
  if (typeof failure === 'number') system.mockResolvedValue(new Response('', { status: failure }))
  else system.mockRejectedValue(new TypeError('fetch failed'))
  const response = new Response('{}')
  const direct = vi.fn<typeof fetch>().mockResolvedValue(response)
  const init = { method: 'POST', headers: { Authorization: 'Bearer test-only' }, body: '{}' }
  expect(await fetchEndpointProbe('https://example.test', init, system, direct)).toBe(response)
  expect(direct).toHaveBeenCalledExactlyOnceWith('https://example.test', expect.objectContaining(init))
})
