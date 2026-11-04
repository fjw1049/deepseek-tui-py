// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { PublishComparisonFile } from '../agent/types'
import { usePublishComparison } from './use-publish-comparison'

const getPublishComparison = vi.fn<(threadId: string) => Promise<PublishComparisonFile[]>>()
vi.mock('../agent/registry', () => ({ getProvider: () => ({ getPublishComparison }) }))

let root: Root
let container: HTMLDivElement

function Probe({ threadId, refreshKey }: { threadId: string | null; refreshKey: string }) {
  const { files, loading } = usePublishComparison(threadId, refreshKey)
  return createElement(
    'div',
    null,
    loading ? 'loading' : files === null ? 'none' : files.map((f) => `${f.path}:${f.stage}`).join(',')
  )
}

beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  getPublishComparison.mockReset()
  container = document.createElement('div')
  root = createRoot(container)
})

afterEach(async () => {
  await act(async () => root.unmount())
  vi.unstubAllGlobals()
})

describe('usePublishComparison', () => {
  it('loads the project-to-chat diff as reviewable files', async () => {
    getPublishComparison.mockResolvedValue([
      { path: 'src/app.ts', status: 'modified', patch: 'diff --git a/src/app.ts b/src/app.ts\n' }
    ])

    await act(async () => root.render(createElement(Probe, { threadId: 't1', refreshKey: 'a' })))

    expect(getPublishComparison).toHaveBeenCalledWith('t1')
    expect(container.textContent).toBe('src/app.ts:unstaged')
  })

  it('reloads when the choice snapshot changes and ignores a stale response', async () => {
    let finishFirst!: (files: PublishComparisonFile[]) => void
    getPublishComparison
      .mockImplementationOnce(() => new Promise((resolve) => { finishFirst = resolve }))
      .mockResolvedValueOnce([{ path: 'b.ts', status: 'added', patch: '' }])

    await act(async () => root.render(createElement(Probe, { threadId: 't1', refreshKey: 'a' })))
    expect(container.textContent).toBe('loading')
    await act(async () => root.render(createElement(Probe, { threadId: 't1', refreshKey: 'b' })))
    await act(async () => finishFirst([{ path: 'a.ts', status: 'modified', patch: '' }]))

    expect(getPublishComparison).toHaveBeenCalledTimes(2)
    expect(container.textContent).toBe('b.ts:unstaged')
  })

  it('does nothing outside the conflicts view', async () => {
    await act(async () => root.render(createElement(Probe, { threadId: null, refreshKey: 'a' })))

    expect(getPublishComparison).not.toHaveBeenCalled()
    expect(container.textContent).toBe('none')
  })
})
