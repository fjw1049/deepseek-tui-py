import { describe, expect, it } from 'vitest'
import type { ChatBlock } from '../agent/types'
import {
  finalizeOrphanRuntimeBlocks,
  hasPendingRuntimeWork,
  moveQueuedMessageToFront
} from './chat-store-runtime-helpers'
import type { QueuedUserMessage } from './chat-store-types'

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
  it('cancels running tools and workflows so pending work clears', () => {
    const blocks: ChatBlock[] = [
      tool('t1', 'running', 'command_execution'),
      tool('t2', 'success', 'file_change'),
      {
        kind: 'workflow',
        id: 'w1',
        toolCallId: 'w1',
        workflowName: 'demo',
        status: 'running',
        snapshot: {
          name: 'demo',
          description: '',
          phases: [],
          logs: [],
          agents: [],
          agent_count: 0,
          running_count: 1,
          done_count: 0,
          error_count: 0
        },
        createdAt: new Date().toISOString()
      },
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
    expect(next.find((b) => b.kind === 'workflow' && b.id === 'w1')).toMatchObject({
      status: 'cancelled'
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
