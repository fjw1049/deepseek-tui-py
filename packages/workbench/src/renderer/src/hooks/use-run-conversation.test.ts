// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useRunConversation } from './use-run-conversation'

const request = vi.fn()
let root: ReturnType<typeof createRoot>
let container: HTMLDivElement
function Probe({ id, refresh = 0 }: { id: string; refresh?: number }) {
  const data = useRunConversation({ kind: 'task', id, threadId: 'parent' }, refresh, true)
  return createElement('div', null, data?.workspace || '')
}
const response = (id: string, status = 'running') => ({ ok: true, body: JSON.stringify({ conversation: { blocks: [], workspace: id, status } }) })
beforeEach(() => {
  vi.useFakeTimers()
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  Object.defineProperty(window, 'dsGui', { configurable: true, value: { runtimeRequest: request } })
  request.mockReset()
  container = document.createElement('div')
  root = createRoot(container)
})
afterEach(async () => {
  await act(async () => root.unmount())
  vi.useRealTimers()
  vi.unstubAllGlobals()
})
it('ignores late snapshots after switching runs and never overlaps requests', async () => {
  let finish!: (value: ReturnType<typeof response>) => void
  request.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve })).mockResolvedValue(response('b', 'completed'))
  await act(async () => root.render(createElement(Probe, { id: 'a' })))
  await act(async () => vi.advanceTimersByTimeAsync(5000))
  expect(request).toHaveBeenCalledTimes(1)
  await act(async () => root.render(createElement(Probe, { id: 'b' })))
  await act(async () => finish(response('a')))
  expect(container.textContent).toBe('b')
  await act(async () => vi.advanceTimersByTimeAsync(5000))
  expect(request).toHaveBeenCalledTimes(2)
})
it('retries temporary failures and refreshes completed history after resume', async () => {
  request.mockRejectedValueOnce(new Error('offline')).mockResolvedValue(response('a', 'completed'))
  await act(async () => root.render(createElement(Probe, { id: 'a' })))
  await act(async () => vi.advanceTimersByTimeAsync(750))
  expect(container.textContent).toBe('a')
  await act(async () => root.render(createElement(Probe, { id: 'a', refresh: 1 })))
  expect(request).toHaveBeenCalledTimes(3)
})
