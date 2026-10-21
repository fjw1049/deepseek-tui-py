import { expect, it, vi } from 'vitest'
const mocks = vi.hoisted(() => ({ createThread: vi.fn(), setState: vi.fn() }))
vi.mock('../../store/chat-store', () => ({ useChatStore: { getState: () => ({ runtimeConnection: 'ready', createThread: mocks.createThread }), setState: mocks.setState } }))
import { usePluginNow } from './use-plugin-now'

it('selects the composer plugin only after creating the chat, without sending a turn', async () => {
  mocks.createThread.mockResolvedValue('thread')
  await usePluginNow('data-analysis')
  expect(mocks.createThread).toHaveBeenCalledWith({ forceNew: true, chats: true })
  expect(mocks.setState).toHaveBeenCalledWith({ pendingPluginSelection: 'data-analysis', route: 'chat' })
  mocks.setState.mockClear()
  mocks.createThread.mockResolvedValue(null)
  await usePluginNow('deep-research')
  expect(mocks.setState).not.toHaveBeenCalled()
})
