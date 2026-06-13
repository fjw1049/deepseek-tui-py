import { describe, expect, it } from 'vitest'

import type { ChatBlock } from '../../agent/types'
import {
  buildSubagentInfrastructureToolIds,
  findFallbackFinalAnswer,
  isSubagentOrchestrationToolName,
  placeAssistantContentBlock,
  reasoningNarrationFromBlocks,
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

describe('placeAssistantContentBlock', () => {
  it('hides mid-turn prefaces from the work trace when a final answer exists', () => {
    const processBlocks: ChatBlock[] = []
    const answerBlocks: Array<Extract<ChatBlock, { kind: 'assistant' }>> = []
    const preface = {
      kind: 'assistant' as const,
      id: 'preface',
      text: '开始探索代码库结构。',
      agentSegment: 'mid_turn_preface' as const
    }
    const finalBlock = {
      kind: 'assistant' as const,
      id: 'final',
      text: '最终分析报告',
      agentSegment: 'final_answer' as const
    }

    placeAssistantContentBlock(
      preface,
      preface,
      {
        hasExplicitFinalAnswer: true,
        isProcessing: false,
        index: 0,
        trailingAssistantContentStart: 99
      },
      processBlocks,
      answerBlocks
    )
    placeAssistantContentBlock(
      finalBlock,
      finalBlock,
      {
        hasExplicitFinalAnswer: true,
        isProcessing: false,
        index: 1,
        trailingAssistantContentStart: 99
      },
      processBlocks,
      answerBlocks
    )

    expect(processBlocks).toHaveLength(0)
    expect(answerBlocks).toEqual([finalBlock])
  })
})

describe('findFallbackFinalAnswer', () => {
  it('promotes the last reasoning block when no explicit final answer exists', () => {
    const blocks: ChatBlock[] = [
      { kind: 'reasoning', id: 'item_r1', text: 'internal trace' },
      { kind: 'reasoning', id: 'item_r2', text: '用户可见正文' }
    ]
    expect(findFallbackFinalAnswer(blocks)).toEqual({
      kind: 'assistant',
      id: 'item_r2',
      text: '用户可见正文',
      agentSegment: 'final_answer'
    })
  })

  it('returns null when a final answer block already exists', () => {
    const blocks: ChatBlock[] = [
      {
        kind: 'assistant',
        id: 'item_a1',
        text: 'done',
        agentSegment: 'final_answer'
      }
    ]
    expect(findFallbackFinalAnswer(blocks)).toBeNull()
  })
})

describe('reasoningNarrationFromBlocks', () => {
  it('returns narration attached to reasoning blocks', () => {
    const blocks: ChatBlock[] = [
      { kind: 'reasoning', id: 'item_r1', text: 'internal', narration: '已理清结构，接下来读取入口' },
      { kind: 'tool', id: 'item_t1', summary: 'read_file', status: 'success', toolKind: 'generic' }
    ]
    expect(reasoningNarrationFromBlocks(blocks)).toBe('已理清结构，接下来读取入口')
  })

  it('ignores reasoning blocks without narration', () => {
    const blocks: ChatBlock[] = [{ kind: 'reasoning', id: 'item_r1', text: 'internal' }]
    expect(reasoningNarrationFromBlocks(blocks)).toBe('')
  })
})
