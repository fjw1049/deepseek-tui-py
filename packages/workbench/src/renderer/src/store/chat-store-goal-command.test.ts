import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useChatStore } from './chat-store'

const mocks = vi.hoisted(() => ({ applyGoalCommand: vi.fn() }))
vi.mock('../agent/registry', () => ({ getProvider: () => mocks }))

const initial = useChatStore.getState()
beforeEach(() => {
  useChatStore.setState({ ...initial, activeThreadId: 'a', runtimeConnection: 'ready',
    refreshThreads: async () => {} }, true)
})
afterEach(() => {
  useChatStore.setState(initial, true)
  vi.clearAllMocks()
})

it('binds budget and resume to one request and ignores a response after switching threads', async () => {
  let release!: (value: unknown) => void
  mocks.applyGoalCommand.mockImplementation(() => new Promise((resolve) => { release = resolve }))
  const pending = useChatStore.getState().applyGoalCommand('budget turns 10', {
    expectedGoalId: 'goal-a', resumeAfterBudget: true
  })
  const goalB = { goal_id: 'goal-b', objective: 'Other work', status: 'paused' as const }
  useChatStore.setState({ activeThreadId: 'b', currentGoal: goalB, busy: false })
  release({ goal: { goal_id: 'goal-a', objective: 'A', status: 'active' }, startedTurn: true })
  expect(await pending).toBe(true)
  expect(mocks.applyGoalCommand).toHaveBeenCalledTimes(1)
  expect(mocks.applyGoalCommand).toHaveBeenCalledWith('a', 'budget turns 10', expect.objectContaining({
    expectedGoalId: 'goal-a', resumeAfterBudget: true
  }))
  expect(useChatStore.getState().currentGoal).toEqual(goalB)
  expect(useChatStore.getState().busy).toBe(false)
})

it('does not write a late command error into another thread', async () => {
  let reject!: (error: Error) => void
  mocks.applyGoalCommand.mockImplementation(() => new Promise((_resolve, fail) => { reject = fail }))
  const pending = useChatStore.getState().applyGoalCommand('resume')
  useChatStore.setState({ activeThreadId: 'b', error: null })
  reject(new Error('A failed'))
  expect(await pending).toBe(false)
  expect(useChatStore.getState().error).toBeNull()
})
