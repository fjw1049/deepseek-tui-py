import { describe, expect, it } from 'vitest'

import type { ChatBlock } from '../../agent/types'
import {
  buildSubagentInfrastructureToolIds,
  isSubagentOrchestrationToolName,
  shouldDefaultExpandProcessSection,
  splitThink
} from './MessageTimeline'

describe('splitThink', () => {
  it('separates closed think tags from visible content', () => {
    expect(splitThink('<think>private reasoning</think>visible answer')).toEqual({
      think: 'private reasoning',
      content: 'visible answer'
    })
  })

  it('supports thinking tag aliases and redacted closing tags', () => {
    expect(splitThink('<thinking>private</thinking>answer')).toEqual({
      think: 'private',
      content: 'answer'
    })
    expect(splitThink('<think>private</redacted_thinking>answer')).toEqual({
      think: 'private',
      content: 'answer'
    })
  })

  it('treats an unterminated think tag as streaming reasoning', () => {
    expect(splitThink('<think>still reasoning')).toEqual({
      think: 'still reasoning',
      content: ''
    })
  })

  it('filters reasoning omitted placeholders from thinking and content', () => {
    expect(splitThink('(reasoning omitted)')).toEqual({
      think: '',
      content: ''
    })
    expect(splitThink('<think>(reasoning omitted)\nreal thought</think>answer')).toEqual({
      think: 'real thought',
      content: 'answer'
    })
    expect(splitThink('answer\n(reasoning omitted)')).toEqual({
      think: '',
      content: 'answer'
    })
  })
})

describe('shouldDefaultExpandProcessSection', () => {
  it('collapses completed execution sections by default', () => {
    expect(
      shouldDefaultExpandProcessSection({
        kind: 'execution',
        active: false,
        hasAttention: false
      })
    ).toBe(false)
  })

  it('expands active or attention-needed execution sections', () => {
    expect(
      shouldDefaultExpandProcessSection({
        kind: 'execution',
        active: true,
        hasAttention: false
      })
    ).toBe(true)
    expect(
      shouldDefaultExpandProcessSection({
        kind: 'execution',
        active: false,
        hasAttention: true
      })
    ).toBe(true)
  })

  it('only expands reasoning while it is active', () => {
    expect(
      shouldDefaultExpandProcessSection({
        kind: 'reasoning',
        active: false,
        hasAttention: true
      })
    ).toBe(false)
  })
})

describe('isSubagentOrchestrationToolName', () => {
  it('recognizes subagent orchestration tools', () => {
    expect(isSubagentOrchestrationToolName('agent_spawn')).toBe(true)
    expect(isSubagentOrchestrationToolName('agent_wait')).toBe(true)
    expect(isSubagentOrchestrationToolName('delegate_to_agent')).toBe(true)
    expect(isSubagentOrchestrationToolName('spawn_agent')).toBe(true)
  })

  it('does not hide ordinary tools', () => {
    expect(isSubagentOrchestrationToolName('read_file')).toBe(false)
    expect(isSubagentOrchestrationToolName('exec_shell')).toBe(false)
    expect(isSubagentOrchestrationToolName(undefined)).toBe(false)
  })
})

describe('buildSubagentInfrastructureToolIds', () => {
  it('hides only successful setup tools before the subagent summary anchor', () => {
    const blocks: ChatBlock[] = [
      {
        kind: 'tool',
        id: 'setup-success',
        summary: 'List dir',
        status: 'success'
      },
      {
        kind: 'tool',
        id: 'setup-error',
        summary: 'Read file',
        status: 'error'
      },
      {
        kind: 'tool',
        id: 'setup-running',
        summary: 'Search files',
        status: 'running'
      },
      {
        kind: 'subagent',
        id: 'subagent-a',
        cardKind: 'delegate',
        agentId: 'agent_a',
        agentType: 'explore',
        status: 'running'
      },
      {
        kind: 'tool',
        id: 'after-subagent',
        summary: 'Read file',
        status: 'success'
      }
    ]

    const ids = buildSubagentInfrastructureToolIds(blocks, {
      anchorBlockId: 'subagent-a',
      blockIds: ['subagent-a'],
      blocks: [blocks[3] as Extract<ChatBlock, { kind: 'subagent' }>],
      total: 1,
      toolFailed: 0,
      pending: 0,
      running: 1,
      completed: 0,
      failed: 0,
      cancelled: 0
    })

    expect([...ids]).toEqual(['setup-success'])
  })
})
