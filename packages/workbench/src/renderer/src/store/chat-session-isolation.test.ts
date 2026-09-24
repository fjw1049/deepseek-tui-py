// @vitest-environment happy-dom
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { ThreadEventSink } from '../agent/types'

const provider = vi.hoisted(() => ({
  getThreadDetail: vi.fn(), subscribeThreadEvents: vi.fn(), interruptTurn: vi.fn(),
  fetchPendingApprovals: vi.fn(), fetchPendingUserInputs: vi.fn(), fetchPendingElevations: vi.fn(),
  warmThread: vi.fn(), submitApprovalDecision: vi.fn(), listThreads: vi.fn(),
  sendUserMessage: vi.fn(), renameThread: vi.fn()
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
  provider.listThreads.mockResolvedValue([])
  provider.sendUserMessage.mockResolvedValue({ turnId: 'turn-a' })
  provider.renameThread.mockResolvedValue(undefined)
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

it('does not restore an old task after recovery finishes late', async () => {
  const pane = session()
  await pane.store.getState().selectThread('a')
  let resolveOld!: (value: ReturnType<typeof snapshot>) => void
  provider.getThreadDetail.mockImplementation((id: string) => id === 'a'
    ? new Promise(resolve => { resolveOld = resolve })
    : Promise.resolve(snapshot(id)))
  const recovery = pane.store.getState().recoverActiveTurn()
  pane.store.setState({ activeThreadId: 'b', currentTurnId: 'turn-b' })
  resolveOld(snapshot('a'))
  await recovery
  expect(pane.store.getState().activeThreadId).toBe('b')
  expect(pane.store.getState().currentTurnId).toBe('turn-b')
})

it('does not attach an old send to a newly selected task after auto-title', async () => {
  const pane = session()
  pane.store.setState({
    activeThreadId: 'a', activeThreadWarmup: { threadId: 'a', status: 'ready' },
    threads: [{ id: 'a', title: '新会话' }, { id: 'b', title: 'B' }] as never,
    blocks: []
  })
  provider.listThreads.mockResolvedValue([{ id: 'a', title: '新会话' }, { id: 'b', title: 'B' }])
  let finishRename!: () => void
  provider.renameThread.mockImplementation(() => new Promise<void>(resolve => { finishRename = resolve }))
  const sending = pane.store.getState().sendMessage('hello')
  await Promise.resolve()
  await Promise.resolve()
  expect(provider.renameThread).toHaveBeenCalledOnce()
  pane.store.setState({ activeThreadId: 'b', currentTurnId: 'turn-b' })
  finishRename()
  await sending
  expect(pane.store.getState().activeThreadId).toBe('b')
  expect(pane.store.getState().currentTurnId).toBe('turn-b')
  expect(provider.subscribeThreadEvents.mock.calls.filter(args => args[0] === 'a')).toHaveLength(0)
})

it('does not retry a queued message while its turn still needs approval', async () => {
  const pane = session()
  const sendMessage = vi.fn(async () => false)
  pane.store.setState({
    sendMessage,
    blocks: [{ kind: 'approval', id: 'gate', approvalId: 'gate', summary: 'Review', status: 'pending' }],
    queuedMessages: [{ id: 'q1', text: 'Next', mode: 'agent' }]
  })
  await pane.store.getState().drainQueuedMessages()
  expect(sendMessage).not.toHaveBeenCalled()
  expect(pane.store.getState().queuedMessages).toHaveLength(1)
})

it('stops draining if a send reports success without consuming the queue head', async () => {
  const pane = session()
  const sendMessage = vi.fn(async () => true)
  pane.store.setState({
    sendMessage,
    queuedMessages: [{ id: 'q1', text: 'Next', mode: 'agent' }]
  })
  await pane.store.getState().drainQueuedMessages()
  expect(sendMessage).toHaveBeenCalledOnce()
  expect(pane.store.getState().queuedMessages).toHaveLength(1)
})

it('drains a waiting message when the last approval is resolved', async () => {
  const pane = session()
  const sendMessage = vi.fn(async () => false)
  pane.store.setState({
    sendMessage,
    blocks: [{ kind: 'approval', id: 'gate', approvalId: 'gate', summary: 'Review', status: 'pending' }],
    queuedMessages: [{ id: 'q1', text: 'Next', mode: 'agent' }]
  })
  pane.store.setState({ blocks: [{ kind: 'approval', id: 'gate', approvalId: 'gate', summary: 'Review', status: 'allowed' }] })
  await Promise.resolve()
  expect(sendMessage).toHaveBeenCalledOnce()
})

it('keeps the newest thread list when an older refresh finishes late', async () => {
  const pane = session()
  let finishOld!: (value: Array<{ id: string; title: string }>) => void
  provider.listThreads.mockImplementationOnce(() => new Promise(resolve => { finishOld = resolve }))
    .mockResolvedValueOnce([{ id: 'a', title: 'New title' }])
  const old = pane.store.getState().refreshThreads()
  await pane.store.getState().refreshThreads()
  finishOld([{ id: 'a', title: 'Old title' }])
  await old
  expect(pane.store.getState().threads[0]?.title).toBe('New title')
})

it('does not reselect the old task while a new selection is loading', async () => {
  const pane = session()
  await pane.store.getState().selectThread('a')
  let finishB!: (value: ReturnType<typeof snapshot>) => void
  provider.getThreadDetail.mockImplementation((id: string) => id === 'b'
    ? new Promise(resolve => { finishB = resolve })
    : Promise.resolve(snapshot(id)))
  provider.listThreads.mockResolvedValue([{ id: 'a', title: 'A' }, { id: 'b', title: 'B' }])
  const selecting = pane.store.getState().selectThread('b')
  await pane.store.getState().refreshThreads()
  expect(provider.getThreadDetail.mock.calls.filter(args => args[0] === 'a')).toHaveLength(1)
  finishB(snapshot('b'))
  await selecting
  expect(pane.store.getState().activeThreadId).toBe('b')
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
