// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useTaskRunDetail } from './use-task-run-detail'
import { fetchTaskDetail, type TaskDetail } from './use-thread-tasks'

vi.mock('./use-thread-tasks', () => ({ fetchTaskDetail: vi.fn() }))
const fetchDetail = vi.mocked(fetchTaskDetail)
const task = (id: string, status: TaskDetail['status'] = 'running'): TaskDetail => ({
  id, status, prompt: id, timeline: [], resultSummary: null, error: null, durationMs: null
})
let root: Root
let container: HTMLDivElement
function Probe({ id }: { id: string }): ReturnType<typeof createElement> {
  const state = useTaskRunDetail(id, 0)
  return createElement('div', null, state.detail?.id ?? (state.failed ? 'failed' : 'loading'))
}
beforeEach(() => {
  vi.useFakeTimers()
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  fetchDetail.mockReset()
  container = document.createElement('div')
  root = createRoot(container)
})
afterEach(async () => {
  await act(async () => root.unmount())
  vi.useRealTimers()
  vi.unstubAllGlobals()
})
describe('visible task progress', () => {
  it('ignores a slow previous task response after switching', async () => {
    let finish!: (detail: TaskDetail) => void
    fetchDetail.mockImplementation((id) => id === 'a'
      ? new Promise((resolve) => { finish = resolve })
      : Promise.resolve(task('b')))
    await act(async () => root.render(createElement(Probe, { id: 'a' })))
    await act(async () => root.render(createElement(Probe, { id: 'b' })))
    await act(async () => finish(task('a')))
    expect(container.textContent).toBe('b')
  })
  it('waits for each request and stops polling on completion', async () => {
    let finish!: (detail: TaskDetail) => void
    fetchDetail.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve }))
    await act(async () => root.render(createElement(Probe, { id: 'a' })))
    await act(async () => vi.advanceTimersByTimeAsync(6000))
    expect(fetchDetail).toHaveBeenCalledTimes(1)
    fetchDetail.mockResolvedValue(task('a', 'completed'))
    await act(async () => finish(task('a')))
    await act(async () => vi.advanceTimersByTimeAsync(1500))
    await act(async () => vi.advanceTimersByTimeAsync(6000))
    expect(fetchDetail).toHaveBeenCalledTimes(2)
  })
  it('retries a temporary failure and closing only stops view polling', async () => {
    fetchDetail.mockRejectedValueOnce(new Error('offline')).mockResolvedValue(task('a'))
    await act(async () => root.render(createElement(Probe, { id: 'a' })))
    expect(container.textContent).toBe('failed')
    await act(async () => vi.advanceTimersByTimeAsync(1500))
    expect(container.textContent).toBe('a')
    await act(async () => root.render(null))
    await act(async () => vi.advanceTimersByTimeAsync(6000))
    expect(fetchDetail).toHaveBeenCalledTimes(2)
  })
})
