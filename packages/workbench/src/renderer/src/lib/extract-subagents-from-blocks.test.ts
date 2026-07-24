import { describe, expect, it } from 'vitest'
import type { ChatBlock } from '../agent/types'
import {
  extractSubagentsFromBlocks,
  isActiveSubagentStatus
} from './extract-subagents-from-blocks'

function subagent(
  partial: Partial<Extract<ChatBlock, { kind: 'subagent' }>> &
    Pick<Extract<ChatBlock, { kind: 'subagent' }>, 'id' | 'agentId' | 'status'>
): Extract<ChatBlock, { kind: 'subagent' }> {
  return {
    kind: 'subagent',
    cardKind: 'delegate',
    agentType: 'explore',
    ...partial
  }
}

describe('extractSubagentsFromBlocks', () => {
  it('keeps only subagent cards', () => {
    const blocks: ChatBlock[] = [
      { kind: 'assistant', id: 'a1', text: 'hi' },
      subagent({ id: 'subagent-1', agentId: 'ag-1', status: 'running', agentType: 'explore' }),
      subagent({ id: 'subagent-2', agentId: 'ag-2', status: 'failed', agentType: 'general' })
    ]
    expect(extractSubagentsFromBlocks(blocks)).toEqual([
      { id: 'subagent-1', agentId: 'ag-1', agentType: 'explore', status: 'running' },
      { id: 'subagent-2', agentId: 'ag-2', agentType: 'general', status: 'failed' }
    ])
  })
})

describe('isActiveSubagentStatus', () => {
  it('treats pending and running as active', () => {
    expect(isActiveSubagentStatus('pending')).toBe(true)
    expect(isActiveSubagentStatus('running')).toBe(true)
    expect(isActiveSubagentStatus('completed')).toBe(false)
    expect(isActiveSubagentStatus('failed')).toBe(false)
    expect(isActiveSubagentStatus('cancelled')).toBe(false)
  })
})
