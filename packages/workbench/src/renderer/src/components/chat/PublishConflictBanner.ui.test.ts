// @vitest-environment happy-dom

import { act, createElement } from 'react'
import { flushSync } from 'react-dom'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { NormalizedThread } from '../../agent/types'
import { useChatStore } from '../../store/chat-store'
import { PublishConflictBanner } from './PublishConflictBanner'

function thread(overrides: Partial<NormalizedThread> = {}): NormalizedThread {
  return {
    id: 'thread-a',
    title: 'Task A',
    createdAt: '2026-08-30T00:00:00Z',
    updatedAt: '2026-08-30T00:00:00Z',
    model: 'deepseek-chat',
    mode: 'agent',
    workspace: '/repo',
    envMode: 'worktree',
    ...overrides
  }
}

describe('PublishConflictBanner recovery controls', () => {
  const initial = useChatStore.getState()
  let container: HTMLDivElement
  let root: Root

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true
    container = document.createElement('div')
    document.body.append(container)
    root = createRoot(container)
  })

  afterEach(() => {
    act(() => root.unmount())
    container.remove()
    useChatStore.setState(initial, true)
    vi.restoreAllMocks()
  })

  it('offers a safe recheck for a missing task workspace', async () => {
    const warmActiveThread = vi.fn(async () => undefined)
    const refreshThreads = vi.fn(async () => undefined)
    useChatStore.setState({
      activeThreadId: 'thread-a',
      busy: false,
      threads: [
        thread({
          publishPending: true,
          publishBlocked: true,
          publishIssue: 'missing'
        })
      ],
      warmActiveThread,
      refreshThreads
    })

    await act(async () => root.render(createElement(PublishConflictBanner)))
    const retry = container.querySelector<HTMLButtonElement>('[data-publish-missing-retry]')
    expect(retry).not.toBeNull()

    await act(async () => retry?.click())
    expect(warmActiveThread).toHaveBeenCalledWith('thread-a')
    expect(refreshThreads).toHaveBeenCalledOnce()
  })

  it('does not leak a late missing-workspace failure into another task', async () => {
    let releaseWarmup: (() => void) | null = null
    const warmActiveThread = vi.fn(
      () => new Promise<void>((resolve) => { releaseWarmup = resolve })
    )
    const refreshThreads = vi.fn(async () => undefined)
    const missing = {
      publishPending: true,
      publishBlocked: true,
      publishIssue: 'missing' as const
    }
    useChatStore.setState({
      activeThreadId: 'thread-a',
      busy: false,
      threads: [thread(missing), thread({ id: 'thread-b', title: 'Task B', ...missing })],
      warmActiveThread,
      refreshThreads
    })

    await act(async () => root.render(createElement(PublishConflictBanner)))
    act(() => {
      container.querySelector<HTMLButtonElement>('[data-publish-missing-retry]')?.click()
    })
    await act(async () => {
      useChatStore.setState({ activeThreadId: 'thread-b' })
      releaseWarmup?.()
      await Promise.resolve()
    })

    expect(warmActiveThread).toHaveBeenCalledWith('thread-a')
    expect(container.querySelector('[data-publish-missing-retry-failed]')).toBeNull()
  })

  it('explains a queued safe sync without showing a decision prompt', async () => {
    useChatStore.setState({
      activeThreadId: 'thread-a',
      busy: false,
      threads: [
        thread({
          publishPending: true,
          publishRequestAction: 'apply',
          publishBlocked: false,
          publishIssue: null,
          publishConflicts: []
        })
      ]
    })

    await act(async () => root.render(createElement(PublishConflictBanner)))

    expect(container.querySelector('[data-publish-waiting]')).not.toBeNull()
    expect(container.querySelector('[data-publish-recovery-banner]')).toBeNull()
    expect(container.querySelector('[data-publish-conflict-banner]')).toBeNull()
  })

  it('keeps an ordinary transient pending sync silent', async () => {
    useChatStore.setState({
      activeThreadId: 'thread-a',
      busy: false,
      threads: [
        thread({
          publishPending: true,
          publishBlocked: false,
          publishIssue: null,
          publishConflicts: []
        })
      ]
    })

    await act(async () => root.render(createElement(PublishConflictBanner)))

    expect(container.innerHTML).toBe('')
  })

  it('drops a confirmation when the runtime snapshot changes', async () => {
    useChatStore.setState({
      activeThreadId: 'thread-a',
      busy: false,
      threads: [
        thread({
          publishPending: true,
          publishBlocked: true,
          publishIssue: 'recovery',
          publishConflicts: ['src/app.ts']
        })
      ]
    })

    await act(async () => root.render(createElement(PublishConflictBanner)))
    await act(async () => {
      container
        .querySelector<HTMLButtonElement>('[data-publish-recovery-choice="use_agent"]')
        ?.click()
    })
    expect(container.querySelector('[data-publish-recovery-confirm]')).not.toBeNull()

    await act(async () => {
      useChatStore.setState({
        threads: [
          thread({
            updatedAt: '2026-08-30T00:00:01Z',
            publishPending: true,
            publishBlocked: true,
            publishIssue: 'recovery',
            publishConflicts: []
          })
        ]
      })
    })

    expect(container.querySelector('[data-publish-recovery-confirm]')).toBeNull()
    expect(
      container.querySelector('[data-publish-recovery-choice="use_agent"]')
    ).toBeNull()
  })

  it('binds a destructive recovery choice to the snapshot being shown', async () => {
    const shownAt = '2026-08-30T00:00:00Z'
    const shownThread = thread({
      updatedAt: shownAt,
      publishPending: true,
      publishBlocked: true,
      publishIssue: 'recovery',
      publishConflicts: ['src/app.ts']
    })
    const resolvePublishConflicts = vi.fn(async () => ({
      status: 'conflict' as const,
      thread: shownThread
    }))
    useChatStore.setState({
      activeThreadId: 'thread-a',
      busy: false,
      threads: [shownThread],
      resolvePublishConflicts
    })

    await act(async () => root.render(createElement(PublishConflictBanner)))
    await act(async () => {
      container
        .querySelector<HTMLButtonElement>('[data-publish-recovery-choice="use_agent"]')
        ?.click()
    })
    await act(async () => {
      container
        .querySelector<HTMLButtonElement>('[data-publish-recovery-action="use_agent"]')
        ?.click()
      await Promise.resolve()
    })

    expect(resolvePublishConflicts).toHaveBeenCalledWith(
      'use_agent',
      undefined,
      shownAt
    )
  })

  it('keeps the selected recovery token when a newer snapshot renders before confirmation', async () => {
    const shownAt = '2026-08-30T00:00:00Z'
    const refreshedAt = '2026-08-30T00:00:01Z'
    const shownThread = thread({
      updatedAt: shownAt,
      publishPending: true,
      publishBlocked: true,
      publishIssue: 'recovery',
      publishConflicts: ['src/app.ts']
    })
    const resolvePublishConflicts = vi.fn(async () => ({
      status: 'conflict' as const,
      thread: shownThread
    }))
    useChatStore.setState({
      activeThreadId: 'thread-a',
      busy: false,
      threads: [shownThread],
      resolvePublishConflicts
    })

    await act(async () => root.render(createElement(PublishConflictBanner)))
    await act(async () => {
      container
        .querySelector<HTMLButtonElement>('[data-publish-recovery-choice="use_agent"]')
        ?.click()
    })

    const confirm = container.querySelector<HTMLButtonElement>(
      '[data-publish-recovery-action="use_agent"]'
    )
    expect(confirm).not.toBeNull()

    act(() => {
      flushSync(() => {
        useChatStore.setState({
          threads: [
            thread({
              updatedAt: refreshedAt,
              publishPending: true,
              publishBlocked: true,
              publishIssue: 'recovery',
              publishConflicts: ['src/app.ts']
            })
          ]
        })
      })
      confirm?.click()
    })
    await act(async () => Promise.resolve())

    expect(resolvePublishConflicts).toHaveBeenCalledWith(
      'use_agent',
      undefined,
      shownAt
    )
  })
})
