import { describe, expect, it } from 'vitest'
import type { ChatBlock } from '../agent/types'
import {
  extractSubagentsFromBlocks,
  isActiveSubagentStatus,
  subagentListTitle
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
      subagent({
        id: 'subagent-1',
        agentId: 'ag-1',
        status: 'running',
        agentType: 'explore',
        prompt: 'Find auth entrypoints'
      }),
      subagent({ id: 'subagent-2', agentId: 'ag-2', status: 'failed', agentType: 'general' })
    ]
    expect(extractSubagentsFromBlocks(blocks)).toEqual([
      {
        id: 'subagent-1',
        agentId: 'ag-1',
        agentType: 'explore',
        prompt: 'Find auth entrypoints',
        status: 'running'
      },
      { id: 'subagent-2', agentId: 'ag-2', agentType: 'general', status: 'failed' }
    ])
  })

  it('backfills prompt from sibling agent spawn tool rows', () => {
    const blocks: ChatBlock[] = [
      {
        kind: 'tool',
        id: 't1',
        summary: 'agent: spawned agent_abc [explore]',
        status: 'success',
        detail: 'spawned agent_abc [explore]',
        meta: {
          tool_name: 'agent',
          agent_id: 'agent_abc',
          tool_input: {
            action: 'spawn',
            agent_type: 'explore',
            prompt: '只查 OperationContextDock 如何渲染 Subagent 列表行'
          }
        }
      },
      subagent({
        id: 'subagent-agent_abc',
        agentId: 'agent_abc',
        status: 'running',
        agentType: 'explore'
      })
    ]
    expect(extractSubagentsFromBlocks(blocks)).toEqual([
      {
        id: 'subagent-agent_abc',
        agentId: 'agent_abc',
        agentType: 'explore',
        prompt: '只查 OperationContextDock 如何渲染 Subagent 列表行',
        status: 'running'
      }
    ])
  })

  it('parses agent_id from spawned result text when meta omits it', () => {
    const blocks: ChatBlock[] = [
      {
        kind: 'tool',
        id: 't1',
        summary: 'agent: spawned agent_xyz [explore]',
        status: 'success',
        detail: 'spawned agent_xyz [explore]',
        meta: {
          tool_name: 'agent',
          tool_input: {
            action: 'spawn',
            prompt: '只查 mailbox started 字段'
          }
        }
      },
      subagent({
        id: 'subagent-agent_xyz',
        agentId: 'agent_xyz',
        status: 'running',
        agentType: 'explore'
      })
    ]
    expect(extractSubagentsFromBlocks(blocks)[0]?.prompt).toBe('只查 mailbox started 字段')
  })
})

describe('subagentListTitle', () => {
  it('prefers spawn prompt over agent type', () => {
    expect(
      subagentListTitle({
        agentId: 'agent_1',
        agentType: 'explore',
        prompt: 'Map the billing module'
      })
    ).toBe('Map the billing module')
  })

  it('falls back to localized type when prompt is missing', () => {
    expect(
      subagentListTitle({ agentId: 'agent_1', agentType: 'explore' }, 56, '子代理')
    ).toBe('探索')
  })

  it('truncates long prompts', () => {
    const prompt = 'A'.repeat(80)
    expect(
      subagentListTitle({ agentId: 'agent_1', agentType: 'explore', prompt }, 20)
    ).toBe(`${'A'.repeat(19)}…`)
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
