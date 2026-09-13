import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { ChatBlock } from '../agent/types'
const provider = vi.hoisted(() => ({
  submitApprovalDecision: vi.fn(), submitEvolutionDecision: vi.fn(), submitElevationDecision: vi.fn(),
  submitUserInputResponse: vi.fn(), fetchPendingApprovals: vi.fn(), fetchPendingUserInputs: vi.fn(),
  connect: vi.fn(), fetchPendingElevations: vi.fn()
}))
vi.mock('../agent/registry', () => ({ getProvider: () => provider }))
import { useChatStore } from './chat-store'

const initial = useChatStore.getState()
beforeEach(() => {
  vi.resetAllMocks()
  provider.fetchPendingApprovals.mockResolvedValue([])
  provider.fetchPendingElevations.mockResolvedValue([])
  provider.fetchPendingUserInputs.mockResolvedValue([])
  vi.stubGlobal('window', { dsGui: { logError: vi.fn(), getSettings: async () => ({ agentProvider: 'deepseek-runtime' }) } })
  useChatStore.setState({ ...initial, activeThreadId: 'a', runtimeConnection: 'ready', loadComposerModels: async () => {} }, true)
})
afterEach(() => { useChatStore.setState(initial, true); vi.unstubAllGlobals() })

it('restores an approval only after the server confirms it is pending', async () => {
  useChatStore.setState({ blocks: [{ kind: 'approval', id: 'gate', approvalId: 'req', summary: 'write', status: 'pending' }] })
  provider.submitApprovalDecision.mockRejectedValue(new Error('Disconnected'))
  await useChatStore.getState().resolveApproval('gate', 'allow')
  expect(useChatStore.getState().blocks[0]).toMatchObject({ status: 'error', submissionFailed: true })
  expect(useChatStore.getState().error).toBeNull()
  await useChatStore.getState().refreshPendingUserInputs()
  expect(useChatStore.getState().blocks[0]).toMatchObject({ status: 'error' })
  provider.fetchPendingApprovals.mockResolvedValue([{ approvalId: 'req', summary: 'write' }])
  await useChatStore.getState().refreshPendingUserInputs()
  expect(useChatStore.getState().blocks[0]).toMatchObject({ status: 'pending', submitting: false })
  expect(provider.submitApprovalDecision).toHaveBeenCalledOnce()
})

it('retains answers through failed submission and authoritative recovery', async () => {
  const answers = [{ id: 'q', label: 'Yes', value: 'Yes' }]
  useChatStore.setState({ blocks: [{ kind: 'user_input', id: 'prompt', requestId: 'req', questions: [], status: 'pending' }] })
  provider.submitUserInputResponse.mockRejectedValue(new Error('Disconnected'))
  await useChatStore.getState().resolveUserInput('prompt', { kind: 'submit', answers })
  expect(useChatStore.getState().error).toBeNull()
  provider.fetchPendingUserInputs.mockResolvedValue([{ requestId: 'req', questions: [] }])
  await useChatStore.getState().refreshPendingUserInputs()
  expect(useChatStore.getState().blocks[0]).toMatchObject({ status: 'pending', answers })
})

it.each(['elevation', 'evolution'] as const)('prevents competing %s decisions', async (kind) => {
  const block: ChatBlock = kind === 'elevation'
    ? { kind, id: 'gate', elevationId: 'req', reason: 'write', elevationKind: 'sandbox', status: 'pending' }
    : { kind, id: 'gate', recordId: 'req', kindLabel: 'skill', summary: 'write', status: 'pending' }
  useChatStore.setState({ blocks: [block] })
  let finish!: () => void
  const submit = kind === 'elevation' ? provider.submitElevationDecision : provider.submitEvolutionDecision
  submit.mockImplementation(() => new Promise<void>(resolve => { finish = resolve }))
  const first = kind === 'elevation' ? useChatStore.getState().resolveElevation('gate', 'allow') : useChatStore.getState().resolveEvolution('gate', 'approve')
  const second = kind === 'elevation' ? useChatStore.getState().resolveElevation('gate', 'deny') : useChatStore.getState().resolveEvolution('gate', 'reject')
  expect(useChatStore.getState().blocks[0]).toMatchObject({ submitting: true })
  finish(); await Promise.all([first, second])
  expect(submit).toHaveBeenCalledOnce()
  expect(useChatStore.getState().blocks[0]).toMatchObject({ submitting: false, status: kind === 'elevation' ? 'allowed' : 'approved' })
})

it('does not leak a late decision failure to another task', async () => {
  useChatStore.setState({ blocks: [{ kind: 'approval', id: 'gate', approvalId: 'req', summary: '', status: 'pending' }] })
  let fail!: (error: Error) => void
  provider.submitApprovalDecision.mockImplementation(() => new Promise((_resolve, reject) => { fail = reject }))
  const request = useChatStore.getState().resolveApproval('gate', 'allow')
  useChatStore.setState({ activeThreadId: 'b', blocks: [], error: 'B error' })
  fail(new Error('A failed')); await request
  expect(useChatStore.getState().error).toBe('B error')
  expect(useChatStore.getState().blocks).toEqual([])
})

it('keeps business errors when a background connection check succeeds', async () => {
  useChatStore.setState({ error: 'File failed', connectionError: 'Offline' })
  await useChatStore.getState().probeRuntime('background')
  expect(useChatStore.getState()).toMatchObject({ error: 'File failed', connectionError: null, runtimeConnection: 'ready' })
})


it('restores an uncertain elevation from the server pending list', async () => {
  useChatStore.setState({ blocks: [{ kind: 'elevation', id: 'gate', elevationId: 'req', reason: 'write', elevationKind: 'sandbox', status: 'error', submissionFailed: true }] })
  provider.fetchPendingElevations.mockResolvedValue([{ elevationId: 'req', reason: 'write', elevationKind: 'sandbox' }])
  await useChatStore.getState().refreshPendingUserInputs()
  expect(useChatStore.getState().blocks[0]).toMatchObject({ status: 'pending', submissionFailed: false })
})
