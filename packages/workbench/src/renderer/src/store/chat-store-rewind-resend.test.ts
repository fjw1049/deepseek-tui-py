import { afterEach, describe, expect, it, vi } from 'vitest'

import { takeComposerRetryDraft } from '../lib/composer-insert'

const provider = vi.hoisted(() => ({
  rewindThread: vi.fn(),
  restoreCode: vi.fn(),
  resolvePublishConflicts: vi.fn(),
  sendUserMessage: vi.fn()
}))

vi.mock('../agent/registry', () => ({
  getProvider: () => provider
}))

import { useChatStore } from './chat-store'

describe('rewind task ownership', () => {
  const initial = useChatStore.getState()

  afterEach(() => {
    takeComposerRetryDraft('thread-a')
    useChatStore.setState(initial, true)
    vi.clearAllMocks()
  })

  it('does not patch or send through another task after an async rewind', async () => {
    let releaseRewind!: (value: null) => void
    provider.rewindThread.mockImplementation(
      () => new Promise<null>((resolve) => { releaseRewind = resolve })
    )
    const taskBBlocks = [
      { kind: 'user' as const, id: 'item_b', text: 'Task B message' }
    ]
    useChatStore.setState({
      activeThreadId: 'thread-a',
      busy: false,
      blocks: [{ kind: 'user', id: 'item_a', text: 'Task A message' }]
    })

    const resend = useChatStore.getState().rewindAndResend('item_a', 'edited wire text', {
      retryDraft: 'edited visible text'
    })
    await vi.waitFor(() => expect(provider.rewindThread).toHaveBeenCalledOnce())
    useChatStore.setState({ activeThreadId: 'thread-b', blocks: taskBBlocks })
    releaseRewind(null)

    await expect(resend).resolves.toBe(false)
    expect(provider.sendUserMessage).not.toHaveBeenCalled()
    expect(useChatStore.getState().blocks).toEqual(taskBBlocks)
    expect(takeComposerRetryDraft('thread-b')).toBeNull()
    expect(takeComposerRetryDraft('thread-a')).toBe('edited visible text')
  })

  it('does not apply a plain rewind patch or notice to a newly active task', async () => {
    let releaseRewind!: (value: null) => void
    provider.rewindThread.mockImplementation(
      () => new Promise<null>((resolve) => { releaseRewind = resolve })
    )
    const taskBBlocks = [
      { kind: 'user' as const, id: 'item_b', text: 'Task B message' }
    ]
    useChatStore.setState({
      activeThreadId: 'thread-a',
      busy: false,
      blocks: [{ kind: 'user', id: 'item_a', text: 'Task A message' }],
      workspaceDirtyTick: 10,
      error: null
    })

    const rewind = useChatStore
      .getState()
      .rewindToMessage('item_a', { restoreFiles: true })
    await vi.waitFor(() => expect(provider.rewindThread).toHaveBeenCalledOnce())
    useChatStore.setState({
      activeThreadId: 'thread-b',
      blocks: taskBBlocks,
      workspaceDirtyTick: 20,
      error: 'Task B notice'
    })
    releaseRewind(null)

    await rewind
    expect(provider.rewindThread).toHaveBeenCalledWith('thread-a', 'item_a', true)
    expect(useChatStore.getState().blocks).toEqual(taskBBlocks)
    expect(useChatStore.getState().workspaceDirtyTick).toBe(20)
    expect(useChatStore.getState().error).toBe('Task B notice')
  })

  it('keeps a late code-restore result scoped to its originating task', async () => {
    let releaseRestore!: (value: {
      restoredFiles: string[]
      skippedFiles: string[]
    }) => void
    provider.restoreCode.mockImplementation(
      () => new Promise((resolve) => { releaseRestore = resolve })
    )
    useChatStore.setState({
      activeThreadId: 'thread-a',
      busy: false,
      workspaceDirtyTick: 10,
      error: null
    })

    const restore = useChatStore.getState().restoreCodeAt('item_a')
    await vi.waitFor(() => expect(provider.restoreCode).toHaveBeenCalledOnce())
    useChatStore.setState({
      activeThreadId: 'thread-b',
      workspaceDirtyTick: 20,
      error: 'Task B notice'
    })
    releaseRestore({ restoredFiles: ['src/a.ts'], skippedFiles: [] })

    await expect(restore).resolves.toEqual({
      restoredFiles: ['src/a.ts'],
      skippedFiles: []
    })
    expect(provider.restoreCode).toHaveBeenCalledWith('thread-a', 'item_a')
    expect(useChatStore.getState().workspaceDirtyTick).toBe(20)
    expect(useChatStore.getState().error).toBe('Task B notice')
  })
})
