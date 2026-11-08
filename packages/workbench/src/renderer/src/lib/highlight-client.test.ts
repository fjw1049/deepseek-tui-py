import { expect, it, vi } from 'vitest'
const state = vi.hoisted(() => ({ workers: [] as { onmessage: ((e: { data: unknown }) => void) | null; postMessage: ReturnType<typeof vi.fn>; terminate: ReturnType<typeof vi.fn> }[] }))
vi.mock('./highlight.worker?worker', () => ({ default: class {
  onmessage = null
  onerror = null
  postMessage = vi.fn()
  terminate = vi.fn()
  constructor() { state.workers.push(this) }
} }))
import { highlightCodeHtml } from './highlight-client'

it('shares consumers, cancels actual abandoned work, and resumes queued work', async () => {
  vi.useFakeTimers()
  const a = new AbortController(), b = new AbortController()
  const first = highlightCodeHtml('one', 'typescript', a.signal)
  const same = highlightCodeHtml('one', 'typescript', b.signal)
  const firstRejected = expect(first).rejects.toMatchObject({ name: 'AbortError' })
  const sameRejected = expect(same).rejects.toMatchObject({ name: 'AbortError' })
  const second = highlightCodeHtml('two', 'typescript')
  const worker = state.workers[0]
  expect(worker.postMessage).toHaveBeenCalledTimes(1)
  a.abort()
  expect(worker.terminate).not.toHaveBeenCalled()
  b.abort()
  expect(worker.terminate).toHaveBeenCalledTimes(1)
  await firstRejected; await sameRejected
  const next = state.workers[1]
  expect(next.postMessage.mock.calls[0][0].code).toBe('two')
  next.onmessage!({ data: { id: next.postMessage.mock.calls[0][0].id, html: '<pre>two</pre>' } })
  expect(await second).toBe('<pre>two</pre>')
  expect(await highlightCodeHtml('two', 'typescript')).toBe('<pre>two</pre>')
  expect(next.postMessage).toHaveBeenCalledTimes(1)
  vi.advanceTimersByTime(30_000)
  expect(next.terminate).toHaveBeenCalledTimes(1)
  vi.useRealTimers()
})
