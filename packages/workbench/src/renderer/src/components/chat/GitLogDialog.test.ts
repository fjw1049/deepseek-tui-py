// @vitest-environment happy-dom

import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { GitLogResult } from '@shared/git-log'
import { GitLogDialog } from './GitLogDialog'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

vi.mock('react-i18next', () => {
  const t = (key: string, values?: Record<string, unknown>): string => {
      if (values?.count !== undefined) return `${key}:${values.count}`
      if (values?.time !== undefined) return `${key}:${values.time}`
      return key
  }
  return { useTranslation: () => ({ t }) }
})

type SuccessfulLog = Extract<GitLogResult, { ok: true }>

function logResult(overrides: Partial<SuccessfulLog> = {}): SuccessfulLog {
  return {
    ok: true,
    repositoryRoot: '/repo',
    branch: 'main',
    headHash: 'head',
    upstream: { ref: 'origin/main', hash: 'head', ahead: 0, behind: 0 },
    hasRemote: true,
    remoteRefreshError: null,
    remoteRefreshedAt: '2026-09-02T00:30:00.000Z',
    commits: [
      {
        hash: 'head',
        shortHash: 'head',
        parents: [],
        subject: 'current commit',
        author: 'tester',
        authoredAt: '2026-09-02T00:20:00.000Z'
      }
    ],
    ...overrides
  }
}

describe('GitLogDialog remote refresh', () => {
  let container: HTMLDivElement
  let root: Root

  beforeEach(() => {
    document.body.innerHTML = ''
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })

  afterEach(async () => {
    await act(async () => root.unmount())
    document.body.innerHTML = ''
    vi.restoreAllMocks()
  })

  async function renderDialog(getGitLog: ReturnType<typeof vi.fn>, workspaceRoot = '/repo'): Promise<void> {
    ;(window as unknown as { dsGui: { getGitLog: typeof getGitLog } }).dsGui = { getGitLog }
    await act(async () => {
      root.render(createElement(GitLogDialog, {
        workspaceRoot,
        currentBranch: 'main',
        open: true,
        onClose: vi.fn()
      }))
    })
  }

  it.each([
    ['gitLogInSync', logResult()],
    ['gitLogAhead:2', logResult({ upstream: { ref: 'origin/main', hash: 'base', ahead: 2, behind: 0 } })],
    ['gitLogBehind:3', logResult({ upstream: { ref: 'origin/main', hash: 'remote', ahead: 0, behind: 3 } })],
    ['gitLogDiverged', logResult({ upstream: { ref: 'origin/main', hash: 'remote', ahead: 2, behind: 1 } })],
    ['gitLogNoUpstream', logResult({ upstream: null })],
    ['gitLogLocalOnly', logResult({ upstream: null, hasRemote: false, remoteRefreshedAt: null })],
    ['gitLogRefreshFailed', logResult({ remoteRefreshError: 'offline', remoteRefreshedAt: null })]
  ])('shows the honest remote state %s', async (expected, response) => {
    const getGitLog = vi.fn().mockResolvedValue(response)
    await renderDialog(getGitLog)

    await vi.waitFor(() => expect(document.body.textContent).toContain(expected))
    expect(getGitLog.mock.calls.slice(0, 2)).toEqual([
      ['/repo', false],
      ['/repo', true]
    ])
  })

  it('keeps the current graph visible while refresh is pending and when IPC fails', async () => {
    let rejectRefresh: (error: Error) => void = () => {}
    const pendingRefresh = new Promise<GitLogResult>((_, reject) => {
      rejectRefresh = reject
    })
    const getGitLog = vi.fn()
      .mockResolvedValueOnce(logResult())
      .mockResolvedValueOnce(logResult())
      .mockReturnValueOnce(pendingRefresh)
    await renderDialog(getGitLog)
    await vi.waitFor(() => expect(document.body.textContent).toContain('current commit'))

    await act(async () => {
      document.body.querySelector<HTMLButtonElement>('[title="gitLogRefresh"]')?.click()
      await Promise.resolve()
    })
    expect(document.body.textContent).toContain('current commit')
    expect(document.body.textContent).toContain('gitLogRefreshing')

    await act(async () => rejectRefresh(new Error('IPC unavailable')))
    await vi.waitFor(() => expect(document.body.textContent).toContain('gitLogRefreshFailed'))
    expect(document.body.textContent).toContain('current commit')
  })

  it('ignores a late response from the previously selected workspace', async () => {
    let resolveOld: (result: GitLogResult) => void = () => {}
    const oldRequest = new Promise<GitLogResult>((resolve) => {
      resolveOld = resolve
    })
    const getGitLog = vi.fn()
      .mockReturnValueOnce(oldRequest)
      .mockResolvedValueOnce(logResult({
        repositoryRoot: '/new-repo',
        commits: [{
          hash: 'new',
          shortHash: 'new',
          parents: [],
          subject: 'new workspace commit',
          author: 'tester',
          authoredAt: '2026-09-02T00:20:00.000Z'
        }]
      }))
      .mockResolvedValueOnce(logResult({
        repositoryRoot: '/new-repo',
        commits: [{
          hash: 'new',
          shortHash: 'new',
          parents: [],
          subject: 'new workspace commit',
          author: 'tester',
          authoredAt: '2026-09-02T00:20:00.000Z'
        }]
      }))
    await renderDialog(getGitLog, '/old-repo')

    await act(async () => {
      root.render(createElement(GitLogDialog, {
        workspaceRoot: '/new-repo',
        currentBranch: 'main',
        open: true,
        onClose: vi.fn()
      }))
    })
    await vi.waitFor(() => expect(document.body.textContent).toContain('new workspace commit'))

    await act(async () => resolveOld(logResult({
      repositoryRoot: '/old-repo',
      commits: [{
        hash: 'old',
        shortHash: 'old',
        parents: [],
        subject: 'old workspace commit',
        author: 'tester',
        authoredAt: '2026-09-02T00:10:00.000Z'
      }]
    })))
    expect(document.body.textContent).toContain('new workspace commit')
    expect(document.body.textContent).not.toContain('old workspace commit')
  })

  it('ignores a late response after the workspace is cleared', async () => {
    let resolveOld: (result: GitLogResult) => void = () => {}
    const oldRequest = new Promise<GitLogResult>((resolve) => {
      resolveOld = resolve
    })
    const getGitLog = vi.fn().mockReturnValueOnce(oldRequest)
    await renderDialog(getGitLog, '/old-repo')

    await act(async () => {
      root.render(createElement(GitLogDialog, {
        workspaceRoot: ' ',
        currentBranch: null,
        open: true,
        onClose: vi.fn()
      }))
    })
    await act(async () => resolveOld(logResult({
      repositoryRoot: '/old-repo',
      commits: [{
        hash: 'old',
        shortHash: 'old',
        parents: [],
        subject: 'old workspace commit',
        author: 'tester',
        authoredAt: '2026-09-02T00:10:00.000Z'
      }]
    })))

    expect(document.body.textContent).not.toContain('old workspace commit')
  })
})
