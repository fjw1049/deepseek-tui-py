import { describe, expect, it } from 'vitest'
import type { GoalSnapshotJson } from '../agent/types'
import { resyncGoalAfterFailedCommand } from './chat-store'
import type { ChatState } from './chat-store-types'

/**
 * A failed `/goal create` is rolled back server-side, but that rollback reaches
 * the UI through no other channel: the HTTP call raised instead of returning
 * the goal, and a create that never started a turn opened no SSE subscription.
 * These lock the re-read that keeps the strip honest.
 */

function activeGoal(objective = 'Ship it'): GoalSnapshotJson {
  return { goal_id: 'goal_1', objective, status: 'active' }
}

/** Minimal state + set/get pair standing in for the Zustand store. */
function harness(initial: Partial<ChatState>) {
  const state = {
    activeThreadId: 'thread_1',
    currentGoal: activeGoal(),
    composerMode: 'goal',
    ...initial
  } as ChatState
  const get = (): ChatState => state
  const set = (
    partial: Partial<ChatState> | ((s: ChatState) => Partial<ChatState>)
  ): void => {
    Object.assign(state, typeof partial === 'function' ? partial(state) : partial)
  }
  return { state, get, set }
}

function providerReturning(goal: GoalSnapshotJson | null) {
  const calls: string[] = []
  return {
    calls,
    provider: {
      getThreadDetail: async (threadId: string) => {
        calls.push(threadId)
        return { blocks: [], latestSeq: 0, goal }
      }
    }
  }
}

describe('resyncGoalAfterFailedCommand', () => {
  it('clears a goal the runtime rolled back and leaves goal mode', async () => {
    const { state, get, set } = harness({})
    const { provider, calls } = providerReturning(null)

    await resyncGoalAfterFailedCommand('thread_1', provider, get, set)

    expect(calls).toEqual(['thread_1'])
    expect(state.currentGoal).toBeNull()
    expect(state.composerMode).toBe('agent')
  })

  it('keeps a goal the runtime deliberately spared (busy-turn create)', async () => {
    // start_turn rejected by a live turn: the backend keeps the fresh goal and
    // chains it when that turn ends, so the strip must keep showing it.
    const survived = activeGoal('Ship during stream')
    const { state, get, set } = harness({})
    const { provider } = providerReturning(survived)

    await resyncGoalAfterFailedCommand('thread_1', provider, get, set)

    expect(state.currentGoal).toEqual(survived)
    expect(state.composerMode).toBe('goal')
  })

  it('drops a late response after the user switched threads', async () => {
    const { state, get, set } = harness({ activeThreadId: 'thread_2' })
    const { provider } = providerReturning(null)

    await resyncGoalAfterFailedCommand('thread_1', provider, get, set)

    // thread_2's goal state must not be overwritten by thread_1's re-read.
    expect(state.currentGoal).toEqual(activeGoal())
    expect(state.composerMode).toBe('goal')
  })

  it('keeps the displayed goal when the re-read itself fails', async () => {
    const { state, get, set } = harness({})
    const provider = {
      getThreadDetail: async () => {
        throw new Error('runtime offline')
      }
    }

    // Must not reject: the caller is already on an error path.
    await resyncGoalAfterFailedCommand('thread_1', provider, get, set)

    expect(state.currentGoal).toEqual(activeGoal())
    expect(state.composerMode).toBe('goal')
  })
})
