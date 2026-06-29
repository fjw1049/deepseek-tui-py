import { describe, expect, it } from 'vitest'

import type { ChatBlock } from '../../agent/types'
import {
  findFallbackFinalAnswer,
  groupProcessRows,
  isSubagentOrchestrationToolName,
  placeAssistantContentBlock,
  reasoningDetailTextFromBlocks,
  reasoningNarrationFromBlocks,
  splitThink
} from './MessageTimeline'
import {
  buildToolRenderContext,
  resolveToolRenderer,
  toolRendererRegistry,
  registerToolRenderers,
  type ToolRenderContext
} from './tool'
import type { ToolBlock } from '../../agent/types'

// Register the built-in renderers once for these tests.
registerToolRenderers()

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

describe('placeAssistantContentBlock', () => {
  it('keeps mid-turn prefaces in the work trace of a finished turn', () => {
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

    expect(processBlocks).toEqual([preface])
    expect(answerBlocks).toEqual([finalBlock])
  })

  it('shows mid-turn prefaces in the work trace while the turn is processing', () => {
    const processBlocks: ChatBlock[] = []
    const answerBlocks: Array<Extract<ChatBlock, { kind: 'assistant' }>> = []
    const preface = {
      kind: 'assistant' as const,
      id: 'preface',
      text: '开始探索代码库结构。',
      agentSegment: 'mid_turn_preface' as const
    }

    placeAssistantContentBlock(
      preface,
      preface,
      {
        hasExplicitFinalAnswer: false,
        isProcessing: true,
        index: 0,
        trailingAssistantContentStart: 99
      },
      processBlocks,
      answerBlocks
    )

    expect(processBlocks).toEqual([preface])
    expect(answerBlocks).toHaveLength(0)
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
      { kind: 'tool', id: 'item_t1', summary: 'read_file', status: 'success', toolKind: 'tool_call' }
    ]
    expect(reasoningNarrationFromBlocks(blocks)).toBe('已理清结构，接下来读取入口')
  })

  it('ignores reasoning blocks without narration', () => {
    const blocks: ChatBlock[] = [{ kind: 'reasoning', id: 'item_r1', text: 'internal' }]
    expect(reasoningNarrationFromBlocks(blocks)).toBe('')
  })
})

describe('reasoningDetailTextFromBlocks', () => {
  it('hides raw reasoning when localized narration is available', () => {
    const blocks: ChatBlock[] = [
      {
        kind: 'reasoning',
        id: 'item_r1',
        text: "Good, I've gathered a lot of information. Let me inspect more files.",
        narration: '已确认基础信息，继续分析核心模块'
      }
    ]

    expect(reasoningDetailTextFromBlocks(blocks)).toBe('')
  })

  it('keeps raw reasoning as a fallback when narration is missing', () => {
    const blocks: ChatBlock[] = [
      { kind: 'reasoning', id: 'item_r1', text: '正在分析项目结构。' },
      { kind: 'reasoning', id: 'item_r2', text: '继续查看核心模块。' }
    ]

    expect(reasoningDetailTextFromBlocks(blocks)).toBe('正在分析项目结构。\n\n继续查看核心模块。')
  })
})

describe('ToolRendererRegistry', () => {
  function block(overrides: Partial<ToolBlock> = {}): ToolBlock {
    return {
      kind: 'tool',
      id: 'tool_1',
      summary: 'read_file: path="src/foo.ts"',
      status: 'success',
      toolKind: 'tool_call',
      ...overrides
    }
  }

  it('resolves a registered tool by exact name', () => {
    const ctx = buildToolRenderContext(block())
    const renderer = resolveToolRenderer(ctx)
    expect(renderer).not.toBeNull()
  })

  it('resolves shell tools to the streaming renderer', () => {
    const ctx = buildToolRenderContext(
      block({ summary: 'exec_shell: ls', toolKind: 'command_execution' })
    )
    const renderer = resolveToolRenderer(ctx)
    expect(renderer).not.toBeNull()
    expect(renderer?.renderWhenPending).toBe(true)
  })

  it('resolves file mutation tools to the diff renderer', () => {
    const ctx = buildToolRenderContext(
      block({ summary: 'edit_file: path="src/foo.ts"', toolKind: 'file_change' })
    )
    const renderer = resolveToolRenderer(ctx)
    expect(renderer).not.toBeNull()
    expect(renderer?.fullBleed).toBe(true)
  })

  it('returns null for an unknown tool', () => {
    const ctx = buildToolRenderContext(block({ summary: 'mystery_tool: x' }))
    // Unknown tools fall through to the registry's default (null), so the
    // ToolCard host renders its built-in header/output.
    expect(resolveToolRenderer(ctx)).toBeNull()
  })

  it('extracts tool name, label, and descriptor from the summary', () => {
    const ctx = buildToolRenderContext(block({ summary: 'read_file: path="src/foo.ts"' }))
    expect(ctx.toolName).toBe('read_file')
    expect(ctx.shortName).toBe('read_file')
    expect(ctx.label).toBe('读取文件')
    expect(ctx.description).toBe('src/foo.ts')
  })

  it('maps runtime status to the renderer state', () => {
    const running = buildToolRenderContext(block({ status: 'running' }))
    const failed = buildToolRenderContext(block({ status: 'error' }))
    const done = buildToolRenderContext(block({ status: 'success' }))
    expect(running.state).toBe('running')
    expect(failed.state).toBe('error')
    expect(done.state).toBe('success')
  })
})

describe('groupProcessRows', () => {
  function toolBlock(id: string, name: string, overrides: Partial<ToolBlock> = {}): ToolBlock {
    return {
      kind: 'tool',
      id,
      summary: `${name}: x`,
      status: 'success',
      toolKind: 'tool_call',
      ...overrides
    }
  }

  it('folds a run of consecutive same-name read-only probes into one batch', () => {
    const blocks: ChatBlock[] = [
      toolBlock('t1', 'read_file'),
      toolBlock('t2', 'read_file'),
      toolBlock('t3', 'read_file'),
      toolBlock('t4', 'read_file'),
      toolBlock('t5', 'read_file')
    ]
    const rows = groupProcessRows(blocks)
    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({ type: 'tool_batch', toolName: 'read_file' })
    expect(rows[0]!.type === 'tool_batch' && rows[0].blocks).toHaveLength(5)
  })

  it('keeps a lone probe as a plain block row', () => {
    const rows = groupProcessRows([toolBlock('t1', 'read_file')])
    expect(rows).toEqual([{ type: 'block', block: expect.objectContaining({ id: 't1' }) }])
  })

  it('breaks the batch on a different tool name', () => {
    const blocks: ChatBlock[] = [
      toolBlock('t1', 'read_file'),
      toolBlock('t2', 'read_file'),
      toolBlock('t3', 'list_dir'),
      toolBlock('t4', 'list_dir')
    ]
    const rows = groupProcessRows(blocks)
    expect(rows).toHaveLength(2)
    expect(rows[0]).toMatchObject({ type: 'tool_batch', toolName: 'read_file' })
    expect(rows[1]).toMatchObject({ type: 'tool_batch', toolName: 'list_dir' })
  })

  it('breaks the batch on an error block and keeps the error on its own row', () => {
    const blocks: ChatBlock[] = [
      toolBlock('t1', 'read_file'),
      toolBlock('t2', 'read_file'),
      toolBlock('t3', 'read_file', { status: 'error' }),
      toolBlock('t4', 'read_file')
    ]
    const rows = groupProcessRows(blocks)
    // batch(t1,t2) + error block(t3) + lone block(t4)
    expect(rows).toHaveLength(3)
    expect(rows[0]).toMatchObject({ type: 'tool_batch' })
    expect(rows[0]!.type === 'tool_batch' && rows[0].blocks).toHaveLength(2)
    expect(rows[1]).toMatchObject({ type: 'block' })
    expect(rows[1]!.type === 'block' && rows[1].block.id).toBe('t3')
    expect(rows[2]).toMatchObject({ type: 'block' })
    expect(rows[2]!.type === 'block' && rows[2].block.id).toBe('t4')
  })

  it('never folds file changes or shell commands', () => {
    const blocks: ChatBlock[] = [
      toolBlock('t1', 'write_file', { toolKind: 'file_change' }),
      toolBlock('t2', 'write_file', { toolKind: 'file_change' }),
      toolBlock('t3', 'exec_shell', { toolKind: 'command_execution' }),
      toolBlock('t4', 'exec_shell', { toolKind: 'command_execution' })
    ]
    const rows = groupProcessRows(blocks)
    expect(rows).toHaveLength(4)
    expect(rows.every((row) => row.type === 'block')).toBe(true)
  })

  it('keeps non-tool blocks as block rows and uses them as batch boundaries', () => {
    const blocks: ChatBlock[] = [
      toolBlock('t1', 'read_file'),
      toolBlock('t2', 'read_file'),
      { kind: 'reasoning', id: 'r1', text: 'thinking' },
      toolBlock('t3', 'read_file'),
      toolBlock('t4', 'read_file')
    ]
    const rows = groupProcessRows(blocks)
    expect(rows).toHaveLength(3)
    expect(rows[0]).toMatchObject({ type: 'tool_batch' })
    expect(rows[1]).toMatchObject({ type: 'block', block: { kind: 'reasoning' } })
    expect(rows[2]).toMatchObject({ type: 'tool_batch' })
  })

  it('excludes subagent orchestration tools from batching', () => {
    const blocks: ChatBlock[] = [
      toolBlock('t1', 'agent_spawn'),
      toolBlock('t2', 'agent_spawn')
    ]
    const rows = groupProcessRows(blocks)
    expect(rows.every((row) => row.type === 'block')).toBe(true)
  })
})

