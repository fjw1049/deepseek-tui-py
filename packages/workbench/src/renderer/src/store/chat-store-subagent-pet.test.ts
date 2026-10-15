// @vitest-environment happy-dom
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { ThreadEventSink } from '../agent/types'
import { subscribePetEvents, type PetActivityEvent } from '../lib/pet/pet-events'

const provider = vi.hoisted(() => ({
  getThreadDetail: vi.fn(), subscribeThreadEvents: vi.fn(), interruptTurn: vi.fn(),
  fetchPendingApprovals: vi.fn(), fetchPendingUserInputs: vi.fn(), fetchPendingElevations: vi.fn(),
  warmThread: vi.fn(), submitApprovalDecision: vi.fn(), listThreads: vi.fn(),
  sendUserMessage: vi.fn(), renameThread: vi.fn(), getThreadPauseState: vi.fn(), steerUserMessage: vi.fn()
}))
vi.mock('../agent/registry', () => ({ getProvider: () => provider }))
import { createChatSessionStore } from './chat-store'

const sessions: ReturnType<typeof createChatSessionStore>[] = []

beforeEach(() => {
  vi.resetAllMocks()
  Object.assign(window, { dsGui: { logError: vi.fn() } })
  provider.getThreadDetail.mockResolvedValue({
    blocks: [], latestSeq: 0, threadStatus: 'running', latestTurnId: 'turn-1', latestUserMessageId: 'user-1'
  })
  provider.fetchPendingApprovals.mockResolvedValue([])
  provider.fetchPendingUserInputs.mockResolvedValue([])
  provider.fetchPendingElevations.mockResolvedValue([])
  provider.subscribeThreadEvents.mockResolvedValue(undefined)
  provider.listThreads.mockResolvedValue([])
})
afterEach(() => { sessions.splice(0).forEach(s => s.dispose()) })

it('drives pet subagent activity from mailbox lifecycle kinds, not progress text', async () => {
  const session = createChatSessionStore()
  sessions.push(session)
  session.store.setState({ runtimeConnection: 'ready', warmActiveThread: async () => {} })
  await session.store.getState().selectThread('t1')
  const sink = provider.subscribeThreadEvents.mock.calls[0][2] as ThreadEventSink
  const events: PetActivityEvent[] = []
  const unsubscribe = subscribePetEvents('t1', (event) => events.push(event))

  // Lifecycle envelopes carry status=null; progress carries narration text.
  sink.onSubagentMailbox?.({ seq: 1, message: { kind: 'started', agent_id: 'agent_a', agent_type: 'explore', status: null } })
  sink.onSubagentMailbox?.({ seq: 2, message: { kind: 'progress', agent_id: 'agent_a', status: 'completed' } })
  sink.onSubagentMailbox?.({ seq: 3, message: { kind: 'failed', agent_id: 'agent_a', status: null, error: 'boom' } })
  unsubscribe()

  expect(events).toEqual([
    { type: 'subagent_started', itemId: 'subagent-agent_a', agentType: 'explore' },
    { type: 'subagent_completed', itemId: 'subagent-agent_a', status: 'failed' }
  ])
})
