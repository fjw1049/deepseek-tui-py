// @vitest-environment happy-dom
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { ThreadEventSink } from '../agent/types'

const provider = vi.hoisted(() => ({
  getThreadDetail: vi.fn(), subscribeThreadEvents: vi.fn(), interruptTurn: vi.fn(),
  fetchPendingApprovals: vi.fn(), fetchPendingUserInputs: vi.fn(), fetchPendingElevations: vi.fn(),
  warmThread: vi.fn(), submitApprovalDecision: vi.fn()
}))
vi.mock('../agent/registry', () => ({ getProvider: () => provider }))
import { createChatSessionStore } from './chat-store'

const sessions: ReturnType<typeof createChatSessionStore>[] = []
function session() {
  const result = createChatSessionStore()
  sessions.push(result)
  result.store.setState({ runtimeConnection: 'ready', warmActiveThread: async () => {} })
  return result
}
const snapshot = (id: string) => ({ blocks: [], latestSeq: 0, threadStatus: 'running', latestTurnId: `turn-${id}`, latestUserMessageId: `user-${id}` })

beforeEach(() => {
  vi.resetAllMocks()
  vi.useFakeTimers()
  Object.assign(window, { dsGui: { logError: vi.fn() } })
  provider.getThreadDetail.mockImplementation(async (id: string) => snapshot(id))
  provider.fetchPendingApprovals.mockResolvedValue([])
  provider.fetchPendingUserInputs.mockResolvedValue([])
  provider.fetchPendingElevations.mockResolvedValue([])
  provider.interruptTurn.mockResolvedValue(undefined)
  provider.subscribeThreadEvents.mockResolvedValue(undefined)
})
afterEach(() => { sessions.splice(0).forEach(s => s.dispose()); vi.useRealTimers() })

it('streams four tasks independently and stops only the requested task', async () => {
  const panes = Array.from({ length: 4 }, session)
  await Promise.all(panes.map((pane, i) => pane.store.getState().selectThread(`${i}`)))
  expect(provider.subscribeThreadEvents).toHaveBeenCalledTimes(4)
  for (let i = 0; i < 4; i++) {
    const call = provider.subscribeThreadEvents.mock.calls.find(args => args[0] === `${i}`)!
    const sink = call[2] as ThreadEventSink
    expect((call[3] as AbortSignal).aborted).toBe(false)
    sink.onDeltas([{ kind: 'agent_message', text: `only-${i}`, seq: 1 }])
  }
  expect(panes.map(p => p.store.getState().liveAssistant)).toEqual(['only-0', 'only-1', 'only-2', 'only-3'])
  await panes[1].store.getState().interrupt()
  expect(provider.interruptTurn).toHaveBeenCalledWith('1', 'turn-1')
  expect(panes.map(p => p.store.getState().busy)).toEqual([true, false, true, true])
  panes[0].dispose()
  const signals = provider.subscribeThreadEvents.mock.calls.map(args => args[3] as AbortSignal)
  expect(signals.filter(s => s.aborted)).toHaveLength(1) // only disposing the view detaches its stream
  expect(signals[2].aborted).toBe(false)
  expect(signals[3].aborted).toBe(false)
})

it('does not let a late selection or stale stream overwrite a newer task', async () => {
  const pane = session()
  let resolveOld!: (value: ReturnType<typeof snapshot>) => void
  provider.getThreadDetail.mockImplementation((id: string) => id === 'old' ? new Promise(resolve => { resolveOld = resolve }) : Promise.resolve(snapshot(id)))
  const old = pane.store.getState().selectThread('old')
  await pane.store.getState().selectThread('new')
  resolveOld(snapshot('old'))
  await old
  expect(pane.store.getState().activeThreadId).toBe('new')
  expect(provider.subscribeThreadEvents).toHaveBeenCalledTimes(1)
  const staleSink = provider.subscribeThreadEvents.mock.calls[0][2] as ThreadEventSink
  await pane.store.getState().selectThread('next')
  staleSink.onDeltas([{ kind: 'agent_message', text: 'stale', seq: 9 }])
  expect(pane.store.getState().liveAssistant).toBe('')
})

it('keeps recovery timers independent when another pane is disposed', async () => {
  const a = session(), b = session()
  await a.store.getState().selectThread('a')
  await b.store.getState().selectThread('b')
  const recoverA = vi.fn(async () => true), recoverB = vi.fn(async () => true)
  a.store.setState({ recoverActiveTurn: recoverA })
  b.store.setState({ recoverActiveTurn: recoverB })
  a.dispose()
  await vi.advanceTimersByTimeAsync(120_001)
  expect(recoverA).not.toHaveBeenCalled()
  expect(recoverB).toHaveBeenCalledOnce()
})


it('routes simultaneous approvals to their own requests even when block IDs match', async () => {
  const a = session(), b = session()
  a.store.setState({ activeThreadId: 'a', blocks: [{ kind: 'approval', id: 'gate', approvalId: 'approval-a', summary: 'A', status: 'pending' }] })
  b.store.setState({ activeThreadId: 'b', blocks: [{ kind: 'approval', id: 'gate', approvalId: 'approval-b', summary: 'B', status: 'pending' }] })
  provider.submitApprovalDecision.mockResolvedValue(undefined)
  await Promise.all([a.store.getState().resolveApproval('gate', 'allow'), b.store.getState().resolveApproval('gate', 'deny')])
  expect(provider.submitApprovalDecision).toHaveBeenCalledWith('approval-a', 'allow', false)
  expect(provider.submitApprovalDecision).toHaveBeenCalledWith('approval-b', 'deny', false)
  expect(a.store.getState().blocks[0]).toMatchObject({ status: 'allowed' })
  expect(b.store.getState().blocks[0]).toMatchObject({ status: 'denied' })
})
