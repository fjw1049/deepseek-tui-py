import { afterEach, beforeEach, expect, it, vi } from 'vitest'

const provider = vi.hoisted(() => ({ updateThread: vi.fn() }))
vi.mock('../agent/registry', () => ({ getProvider: () => provider }))

import { createChatSessionStore } from './chat-store'

let session: ReturnType<typeof createChatSessionStore>
const thread = {
  id: 'origin', title: 'origin', updatedAt: '', model: 'initial-model', provider: 'endpoint', mode: 'agent'
}

beforeEach(() => {
  provider.updateThread.mockReset()
  session = createChatSessionStore()
  session.store.setState({
    activeThreadId: thread.id, threads: [thread], composerModel: 'endpoint::initial-model',
    runtimeConnection: 'ready'
  })
})

afterEach(() => { session.dispose() })

it('saves model selection to the current thread without sending a message', async () => {
  provider.updateThread.mockResolvedValue({ ...thread, provider: 'custom-vendor', model: 'anything-new' })
  session.store.getState().setComposerModel('custom-vendor::anything-new')
  await vi.waitFor(() => {
    expect(provider.updateThread).toHaveBeenCalledWith('origin', {
      provider: 'custom-vendor', model: 'anything-new'
    })
    expect(session.store.getState().threads[0].model).toBe('anything-new')
  })
  expect(session.store.getState().blocks).toEqual([])
})

it('serializes rapid selections so the newest route is saved last', async () => {
  let resolveFirst!: (value: typeof thread) => void
  provider.updateThread.mockImplementationOnce(() => new Promise((resolve) => {
    resolveFirst = resolve
  }))
  provider.updateThread.mockResolvedValueOnce({ ...thread, provider: 'other', model: 'latest' })
  session.store.getState().setComposerModel('endpoint::first')
  session.store.getState().setComposerModel('other::latest')
  await vi.waitFor(() => expect(provider.updateThread).toHaveBeenCalledTimes(1))
  resolveFirst({ ...thread, model: 'first' })
  await vi.waitFor(() => {
    expect(provider.updateThread).toHaveBeenCalledTimes(2)
    expect(session.store.getState().threads[0].model).toBe('latest')
  })
  expect(session.store.getState().composerModel).toBe('other::latest')
})

it('restores the previous choice and shows a failed synchronization', async () => {
  provider.updateThread.mockRejectedValueOnce(new Error('configuration unavailable'))
  session.store.getState().setComposerModel('other::new-model')
  await vi.waitFor(() => {
    expect(session.store.getState().composerModel).toBe('endpoint::initial-model')
    expect(session.store.getState().error).toBe('configuration unavailable')
  })
})

it('does not change an existing chat when choosing a model before creating a chat', async () => {
  session.store.setState({ activeThreadId: null })
  session.store.getState().setComposerModel('custom::next-model')
  await Promise.resolve()
  expect(provider.updateThread).not.toHaveBeenCalled()
  expect(session.store.getState().composerModel).toBe('custom::next-model')
})


it('keeps the provider when successive synchronization requests fail', async () => {
  provider.updateThread.mockRejectedValue(new Error('offline'))
  session.store.getState().setComposerModel('first-vendor::first')
  session.store.getState().setComposerModel('second-vendor::second')
  await vi.waitFor(() => {
    expect(provider.updateThread).toHaveBeenCalledTimes(2)
    expect(session.store.getState().composerModel).toBe('endpoint::initial-model')
  })
})
