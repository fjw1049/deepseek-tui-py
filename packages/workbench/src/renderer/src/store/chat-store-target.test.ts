import { afterEach, beforeEach, expect, it, vi } from 'vitest'
const provider = vi.hoisted(() => ({ createThread: vi.fn() }))
vi.mock('../agent/registry', () => ({ getProvider: () => provider }))
import { createChatSessionStore } from './chat-store'
let session: ReturnType<typeof createChatSessionStore>
beforeEach(() => {
  session = createChatSessionStore()
  session.store.setState({ runtimeConnection: 'ready', activeThreadId: 'old', threads: [], workspaceRoot: '/repo' })
  vi.stubGlobal('window', { dsGui: { getSettings: vi.fn().mockResolvedValue({ workspaceRoot: '/repo' }) } })
})
afterEach(() => { session.dispose(); vi.unstubAllGlobals() })
it('returns no target when creating a new conversation fails', async () => {
  provider.createThread.mockRejectedValueOnce(new Error('offline'))
  expect(await session.store.getState().createThread({ workspaceRoot: '/repo', forceNew: true })).toBeNull()
  expect(session.store.getState().activeThreadId).toBe('old')
})
it('rejects a message explicitly addressed to a different conversation', async () => {
  expect(await session.store.getState().sendMessage('do work', undefined, { expectedThreadId: 'target' })).toBe(false)
  expect(session.store.getState().blocks).toEqual([])
})
