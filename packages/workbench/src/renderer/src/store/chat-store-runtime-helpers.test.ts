import { describe, expect, it } from 'vitest'
import type { ChatBlock, NormalizedThread } from '../agent/types'
import {
  findReusableEmptyThreadId,
  finalizeOrphanRuntimeBlocks,
  hasPendingRuntimeWork,
  mergePendingUserInputBlocks,
  moveQueuedMessageToFront
} from './chat-store-runtime-helpers'
import type { ChatState, QueuedUserMessage } from './chat-store-types'

function tool(
  id: string,
  status: 'running' | 'success' | 'error',
  toolKind: 'tool_call' | 'command_execution' | 'file_change' = 'tool_call'
): ChatBlock {
  return {
    kind: 'tool',
    id,
    createdAt: new Date().toISOString(),
    summary: id,
    status,
    toolKind
  }
}

describe('finalizeOrphanRuntimeBlocks', () => {
  it('cancels running tools and subagents so pending work clears', () => {
    const blocks: ChatBlock[] = [
      tool('t1', 'running', 'command_execution'),
      tool('t2', 'success', 'file_change'),
      {
        kind: 'subagent',
        id: 's1',
        createdAt: new Date().toISOString(),
        agentId: 'a1',
        agentType: 'explore',
        cardKind: 'delegate',
        status: 'running',
        summary: 'running agent'
      }
    ]

    expect(blocks.some(hasPendingRuntimeWork)).toBe(true)
    const next = finalizeOrphanRuntimeBlocks(blocks)
    expect(next.some(hasPendingRuntimeWork)).toBe(false)
    expect(next.find((b) => b.kind === 'tool' && b.id === 't1')).toMatchObject({
      status: 'error'
    })
    expect(next.find((b) => b.kind === 'subagent' && b.id === 's1')).toMatchObject({
      status: 'cancelled'
    })
    expect(next.find((b) => b.kind === 'tool' && b.id === 't2')).toMatchObject({
      status: 'success'
    })
  })

  it('returns the same array when nothing is pending', () => {
    const blocks: ChatBlock[] = [tool('t1', 'success')]
    expect(finalizeOrphanRuntimeBlocks(blocks)).toBe(blocks)
  })
})

describe('mergePendingUserInputBlocks', () => {
  it('adds bridged task prompts even when none exist in thread detail', () => {
    const blocks: ChatBlock[] = [tool('t1', 'success')]
    const merged = mergePendingUserInputBlocks(blocks, [
      {
        requestId: 'call_plan',
        taskId: 'task_heap',
        questions: [
          {
            id: 'enter_plan',
            header: '规划模式',
            question: '进入？',
            options: [{ label: '进入', description: '', value: 'enter' }]
          }
        ]
      }
    ])
    expect(merged.firstAddedBlockId).toBe('call_plan')
    const card = merged.blocks.find((b) => b.kind === 'user_input')
    expect(card).toMatchObject({
      kind: 'user_input',
      requestId: 'call_plan',
      taskId: 'task_heap',
      status: 'pending'
    })
  })
})

describe('moveQueuedMessageToFront', () => {
  const queued: QueuedUserMessage[] = [
    { id: 'q1', text: 'first' },
    { id: 'q2', text: 'second' },
    { id: 'q3', text: 'third' }
  ]

  it('moves a mid-queue message to the front', () => {
    expect(moveQueuedMessageToFront(queued, 'q3')?.map((m) => m.id)).toEqual([
      'q3',
      'q1',
      'q2'
    ])
  })

  it('returns the same array when already first', () => {
    expect(moveQueuedMessageToFront(queued, 'q1')).toBe(queued)
  })

  it('returns null when the id is missing', () => {
    expect(moveQueuedMessageToFront(queued, 'missing')).toBeNull()
  })
})

function emptyThread(
  id: string,
  overrides: Partial<NormalizedThread> = {}
): NormalizedThread {
  return {
    id,
    title: id,
    updatedAt: '2026-08-30T00:00:00.000Z',
    model: 'deepseek-chat',
    mode: 'agent',
    workspace: '/repo',
    ...overrides
  }
}

describe('findReusableEmptyThreadId', () => {
  const unsafePublishStates: Array<[string, Partial<NormalizedThread>]> = [
    ['pending publish', { publishPending: true }],
    ['blocked publish', { publishBlocked: true }],
    ['structured publish issue', { publishIssue: 'failure' }],
    ['file conflict', { publishConflicts: ['src/app.ts'] }],
    ['recovery state', { publishConflicts: ['<unpublished-worktree-labor>'] }],
    ['failed publish', { publishConflicts: ['<publish-failed>'] }]
  ]

  it.each(unsafePublishStates)(
    'does not reuse an active empty thread with %s',
    async (_label, overrides) => {
      const active = emptyThread('active', overrides)
      const state = {
        activeThreadId: active.id,
        threads: [active],
        blocks: []
      } as unknown as ChatState

      const reusable = await findReusableEmptyThreadId(
        state,
        { getThreadDetail: async () => ({ blocks: [] }) },
        '/repo'
      )

      expect(reusable).toBeNull()
    }
  )

  it('skips all unsafe empty candidates and reuses the next clean one', async () => {
    const unsafe = unsafePublishStates.map(([, overrides], index) =>
      emptyThread(`unsafe-${index}`, {
        ...overrides,
        updatedAt: `2026-08-30T0${index + 2}:00:00.000Z`
      })
    )
    const clean = emptyThread('clean', {
      updatedAt: '2026-08-30T01:00:00.000Z'
    })
    const calls: string[] = []
    const state = {
      activeThreadId: null,
      threads: [...unsafe, clean],
      blocks: []
    } as unknown as ChatState

    const reusable = await findReusableEmptyThreadId(
      state,
      {
        getThreadDetail: async (threadId) => {
          calls.push(threadId)
          return { blocks: [] }
        }
      },
      '/repo'
    )

    expect(reusable).toBe('clean')
    expect(calls).toEqual(['clean'])
  })

  it('continues to reuse a clean active empty thread', async () => {
    const active = emptyThread('active')
    const state = {
      activeThreadId: active.id,
      threads: [active],
      blocks: []
    } as unknown as ChatState

    const reusable = await findReusableEmptyThreadId(
      state,
      { getThreadDetail: async () => ({ blocks: [] }) },
      '/repo'
    )

    expect(reusable).toBe('active')
  })

  it('uses the latest runtime publish state before reusing an active task', async () => {
    const active = emptyThread('active')
    const state = {
      activeThreadId: active.id,
      threads: [active],
      blocks: []
    } as unknown as ChatState

    const reusable = await findReusableEmptyThreadId(
      state,
      {
        getThreadDetail: async () => ({ blocks: [] }),
        listThreads: async () => [
          emptyThread('active', { publishIssue: 'recovery', publishBlocked: true })
        ]
      },
      '/repo'
    )

    expect(reusable).toBeNull()
  })
})
