// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { TaskFiles } from './TaskFiles'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
let root: Root
let container: HTMLDivElement
const runtimeRequest = vi.fn()
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  Object.defineProperty(window, 'dsGui', { configurable: true, value: { runtimeRequest } })
  runtimeRequest.mockReset()
  container = document.createElement('div')
  document.body.append(container)
  root = createRoot(container)
})
afterEach(async () => {
  await act(async () => root.unmount())
  container.remove()
  vi.unstubAllGlobals()
})
const response = (paths = { 'file.txt': 'restored' }, restored = false) => ({
  ok: true, body: JSON.stringify({ workspace: '/workspace', paths,
    report: { restored: restored ? ['file.txt'] : [], merged: [], conflicted: [], skipped: [] },
    resume_blocked: restored })
})

it('previews first and only restores after a second explicit click', async () => {
  const onRestored = vi.fn()
  runtimeRequest.mockResolvedValueOnce(response()).mockResolvedValueOnce(response(undefined, true))
  await act(async () => root.render(createElement(TaskFiles, { taskId: 'task/1', onRestored })))
  expect(runtimeRequest).not.toHaveBeenCalled()
  await act(async () => container.querySelector('button')!.click())
  expect(runtimeRequest).toHaveBeenCalledWith('/v1/tasks/task%2F1/files', 'GET')
  expect(container.textContent).toContain('file.txt')
  expect(container.textContent).toContain('taskFiles.scope')
  expect(onRestored).not.toHaveBeenCalled()
  await act(async () => [...container.querySelectorAll('button')].find((b) => b.textContent === 'taskFiles.confirm')!.click())
  expect(runtimeRequest).toHaveBeenLastCalledWith('/v1/tasks/task%2F1/files/restore', 'POST')
  expect(onRestored).toHaveBeenCalledOnce()
  expect(container.textContent).toContain('taskFiles.resumeBlocked')
  expect(container.querySelector('[role="status"]')).not.toBeNull()
})

it('offers no restore action for conflicting files and exposes loading failures locally', async () => {
  runtimeRequest.mockResolvedValueOnce(response({ 'file.txt': 'conflicted' }))
    .mockResolvedValueOnce({ ok: false, body: 'checkpoint unavailable' })
  await act(async () => root.render(createElement(TaskFiles, { taskId: 't', onRestored: vi.fn() })))
  await act(async () => container.querySelector('button')!.click())
  expect(container.textContent).toContain('taskFiles.conflicted')
  expect(container.textContent).not.toContain('taskFiles.confirmHint')
  await act(async () => container.querySelector('button')!.click())
  expect(container.querySelector('[role="alert"]')?.textContent).toBe('checkpoint unavailable')
  expect(runtimeRequest.mock.calls.every((call) => call[1] === 'GET')).toBe(true)
})
