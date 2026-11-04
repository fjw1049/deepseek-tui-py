// @vitest-environment happy-dom

import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { NormalizedThread } from '../../agent/types'
import { useChatStore } from '../../store/chat-store'
import { OPEN_CHANGES_PANEL_EVENT, type ChangeReviewRequest } from '../../lib/change-review'
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

describe('PublishConflictBanner choices', () => {
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

  it('shows a lost copy and unknown leftovers as one way forward from the project', async () => {
    useChatStore.setState({
      activeThreadId: 'thread-a',
      busy: false,
      threads: [thread({ publishPending: true, publishBlocked: true, publishIssue: 'missing' })]
    })
    await act(async () => root.render(createElement(PublishConflictBanner)))
    const missingText = container.textContent
    const buttons = container.querySelectorAll('button')

    expect(buttons).toHaveLength(1)
    expect(buttons[0]?.getAttribute('data-publish-choice')).toBe('keep_project')

    await act(async () => {
      useChatStore.setState({
        threads: [thread({ publishBlocked: true, publishIssue: 'recovery', publishConflicts: [] })]
      })
    })

    expect(container.textContent).toBe(missingText)
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
    expect(container.querySelector('[data-publish-choice-banner]')).toBeNull()
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

  it('shows conflicts and recovery as the same version choice', async () => {
    useChatStore.setState({
      activeThreadId: 'thread-a',
      busy: false,
      threads: [thread({ publishBlocked: true, publishConflicts: ['src/app.ts'] })]
    })
    await act(async () => root.render(createElement(PublishConflictBanner)))
    const conflictText = container.textContent

    await act(async () => {
      useChatStore.setState({
        threads: [
          thread({
            publishBlocked: true,
            publishIssue: 'recovery',
            publishConflicts: ['src/app.ts']
          })
        ]
      })
    })

    expect(container.querySelector('[data-publish-choice-banner="recovery"]')).not.toBeNull()
    expect(container.textContent).toBe(conflictText)
  })

  it('asks once before replacing project files with the chat version', async () => {
    const resolvePublishConflicts = vi.fn(async () => ({
      status: 'applied' as const,
      thread: thread()
    }))
    useChatStore.setState({
      activeThreadId: 'thread-a',
      busy: false,
      threads: [thread({ publishBlocked: true, publishConflicts: ['src/app.ts'] })],
      resolvePublishConflicts
    })

    await act(async () => root.render(createElement(PublishConflictBanner)))
    await act(async () => {
      container.querySelector<HTMLButtonElement>('[data-publish-choice="use_agent"]')?.click()
    })

    expect(resolvePublishConflicts).not.toHaveBeenCalled()
    expect(container.querySelector('[data-publish-confirm]')).not.toBeNull()

    await act(async () => {
      container
        .querySelector<HTMLButtonElement>('[data-publish-confirm-action="use_agent"]')
        ?.click()
      await Promise.resolve()
    })

    expect(resolvePublishConflicts).toHaveBeenCalledWith(
      'use_agent',
      undefined,
      '2026-08-30T00:00:00Z'
    )
  })

  it('opens the project-to-chat diff for all files or one file', async () => {
    const requests: ChangeReviewRequest[] = []
    const listener = (event: Event): void => {
      requests.push((event as CustomEvent<ChangeReviewRequest>).detail)
    }
    window.addEventListener(OPEN_CHANGES_PANEL_EVENT, listener)
    useChatStore.setState({
      activeThreadId: 'thread-a',
      busy: false,
      threads: [thread({ publishBlocked: true, publishConflicts: ['src/app.ts'] })]
    })

    await act(async () => root.render(createElement(PublishConflictBanner)))
    await act(async () => {
      container.querySelector<HTMLButtonElement>('[data-publish-review]')?.click()
      container.querySelector<HTMLButtonElement>('li button[title="src/app.ts"]')?.click()
    })
    window.removeEventListener(OPEN_CHANGES_PANEL_EVENT, listener)

    expect(requests).toEqual([
      { context: 'conflicts' },
      { context: 'conflicts', path: 'src/app.ts' }
    ])
  })

  it('lets a missing workspace start over from the project after one confirmation', async () => {
    const resolvePublishConflicts = vi.fn(async () => ({
      status: 'applied' as const,
      thread: thread()
    }))
    useChatStore.setState({
      activeThreadId: 'thread-a',
      busy: false,
      threads: [
        thread({ publishPending: true, publishBlocked: true, publishIssue: 'missing' })
      ],
      resolvePublishConflicts
    })

    await act(async () => root.render(createElement(PublishConflictBanner)))
    await act(async () => {
      container.querySelector<HTMLButtonElement>('[data-publish-choice="keep_project"]')?.click()
    })
    expect(resolvePublishConflicts).not.toHaveBeenCalled()
    await act(async () => {
      container
        .querySelector<HTMLButtonElement>('[data-publish-confirm-action="keep_project"]')
        ?.click()
      await Promise.resolve()
    })

    expect(resolvePublishConflicts).toHaveBeenCalledWith(
      'keep_project',
      undefined,
      '2026-08-30T00:00:00Z'
    )
  })

  it('drops a confirmation and says why when the files change', async () => {
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
      container.querySelector<HTMLButtonElement>('[data-publish-choice="use_agent"]')?.click()
    })
    expect(container.querySelector('[data-publish-confirm]')).not.toBeNull()

    await act(async () => {
      useChatStore.setState({
        threads: [
          thread({
            updatedAt: '2026-08-30T00:00:01Z',
            publishPending: true,
            publishBlocked: true,
            publishIssue: 'recovery',
            publishConflicts: ['src/app.ts', 'src/other.ts']
          })
        ]
      })
    })

    expect(container.querySelector('[data-publish-confirm]')).toBeNull()
    expect(container.querySelector('[data-publish-changed]')).not.toBeNull()
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
      container.querySelector<HTMLButtonElement>('[data-publish-choice="use_agent"]')?.click()
    })
    // An unrelated refresh of the same question keeps the confirmation open
    // and the token of the state the user chose from.
    await act(async () => {
      useChatStore.setState({
        threads: [{ ...shownThread, updatedAt: '2026-08-30T00:00:01Z' }]
      })
    })
    await act(async () => {
      container
        .querySelector<HTMLButtonElement>('[data-publish-confirm-action="use_agent"]')
        ?.click()
      await Promise.resolve()
    })

    expect(resolvePublishConflicts).toHaveBeenCalledWith('use_agent', undefined, shownAt)
    // The runtime refused the stale choice: the user is told, not left guessing.
    expect(container.querySelector('[data-publish-changed]')).not.toBeNull()
    expect(container.querySelector('[data-publish-confirm]')).toBeNull()
  })
})
