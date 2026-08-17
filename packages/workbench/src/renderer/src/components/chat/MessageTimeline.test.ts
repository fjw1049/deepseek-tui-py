import { describe, expect, it } from 'vitest'

import type { ChatBlock } from '../../agent/types'
import {
  clipMidTurnPrefaceText,
  computeTailAnchorScrollTop,
  computeTailAnchorSpacerPx,
  findLastLiveWorkRowId,
  shouldParseIncompleteAssistantMarkdown,
  groupProcessRows,
  isSubagentOrchestrationToolName,
  isInternalSubagentHandoffSystemText,
  placeAssistantContentBlock,
  planProcessRenderChunks,
  reasoningDetailTextFromBlocks,
  reasoningNarrationFromBlocks,
  shouldReleaseTailAnchor,
  splitThink,
  trailingThinkingIndicatorId
} from './message-timeline-logic'
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
    expect(isSubagentOrchestrationToolName('agent')).toBe(true)
    expect(isSubagentOrchestrationToolName('agent_resume')).toBe(true)
    // Legacy tool names from pre-merge history transcripts.
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

describe('isInternalSubagentHandoffSystemText', () => {
  it('detects wait/resume handoff chrome', () => {
    expect(isInternalSubagentHandoffSystemText('Waiting on 1 sub-agent(s) to complete...')).toBe(
      true
    )
    expect(
      isInternalSubagentHandoffSystemText('Resuming turn with 1 sub-agent completion(s)')
    ).toBe(true)
    expect(isInternalSubagentHandoffSystemText('Task completed')).toBe(false)
  })
})

describe('shouldParseIncompleteAssistantMarkdown', () => {
  it('is only true for the live answer bubble', () => {
    expect(shouldParseIncompleteAssistantMarkdown(true)).toBe(true)
    expect(shouldParseIncompleteAssistantMarkdown(false)).toBe(false)
  })
})

describe('clipMidTurnPrefaceText', () => {
  it('keeps short single-line prefaces intact', () => {
    expect(clipMidTurnPrefaceText('开始探索代码库结构。')).toEqual({
      preview: '开始探索代码库结构。',
      clipped: false
    })
  })

  it('clips long prefaces and multi-line repair plans', () => {
    const plan = [
      '所有修复点的代码上下文已确认。现在列计划，请批准后批量执行。',
      '',
      '## 修复计划',
      '',
      '针对审核报告里的 C1、C2、C3、H1 四个 bug，做以下最小侵入修复。'
    ].join('\n')
    const clipped = clipMidTurnPrefaceText(plan)
    expect(clipped.clipped).toBe(true)
    expect(clipped.preview.endsWith('…')).toBe(true)
    expect(clipped.preview.includes('## 修复计划')).toBe(false)
    expect(clipped.preview.length).toBeLessThan(plan.length)
  })
})

describe('placeAssistantContentBlock', () => {
  it('routes blocks purely by their persisted segment metadata', () => {
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

    placeAssistantContentBlock(preface, preface, processBlocks, answerBlocks)
    placeAssistantContentBlock(finalBlock, finalBlock, processBlocks, answerBlocks)

    expect(processBlocks).toEqual([preface])
    expect(answerBlocks).toEqual([finalBlock])
  })

  it('never promotes an untagged assistant block to the answer bubble', () => {
    const processBlocks: ChatBlock[] = []
    const answerBlocks: Array<Extract<ChatBlock, { kind: 'assistant' }>> = []
    const untagged = {
      kind: 'assistant' as const,
      id: 'legacy',
      text: '一段没有元数据的历史消息'
    }

    placeAssistantContentBlock(untagged, untagged, processBlocks, answerBlocks)

    expect(processBlocks).toEqual([untagged])
    expect(answerBlocks).toHaveLength(0)
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

  it('folds a lone probe into a one-item batch', () => {
    const rows = groupProcessRows([toolBlock('t1', 'read_file')])
    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({ type: 'tool_batch', toolName: 'read_file' })
    expect(rows[0]!.type === 'tool_batch' && rows[0].blocks).toHaveLength(1)
  })

  it('folds mixed consecutive probe tool names into one batch', () => {
    const blocks: ChatBlock[] = [
      toolBlock('t1', 'read_file'),
      toolBlock('t2', 'read_file'),
      toolBlock('t3', 'list_dir'),
      toolBlock('t4', 'list_dir')
    ]
    const rows = groupProcessRows(blocks)
    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({
      type: 'tool_batch',
      toolName: 'probe',
      mixed: true
    })
    expect(rows[0]!.type === 'tool_batch' && rows[0].blocks).toHaveLength(4)
  })

  it('folds error and running probes into the same batch as successes', () => {
    const blocks: ChatBlock[] = [
      toolBlock('t1', 'read_file'),
      toolBlock('t2', 'read_file'),
      toolBlock('t3', 'read_file', { status: 'error' }),
      toolBlock('t4', 'read_file', { status: 'running' })
    ]
    const rows = groupProcessRows(blocks)
    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({ type: 'tool_batch', toolName: 'read_file' })
    expect(rows[0]!.type === 'tool_batch' && rows[0].blocks).toHaveLength(4)
  })

  it('never folds file changes or mutating shells', () => {
    const blocks: ChatBlock[] = [
      toolBlock('t1', 'write_file', { toolKind: 'file_change' }),
      toolBlock('t2', 'write_file', { toolKind: 'file_change' }),
      toolBlock('t3', 'exec_shell', {
        toolKind: 'command_execution',
        summary: 'exec_shell: npm test',
        meta: { tool_input: { command: 'npm test' } }
      }),
      toolBlock('t4', 'exec_shell', {
        toolKind: 'command_execution',
        summary: 'exec_shell: npm test',
        meta: { tool_input: { command: 'npm test' } }
      })
    ]
    const rows = groupProcessRows(blocks)
    expect(rows).toHaveLength(4)
    expect(rows.every((row) => row.type === 'block')).toBe(true)
  })

  it('folds consecutive probe shells into one batch', () => {
    const blocks: ChatBlock[] = [
      toolBlock('t1', 'exec_shell', {
        toolKind: 'command_execution',
        summary: 'exec_shell: ls -la && find . -maxdepth 2',
        meta: { tool_input: { command: 'ls -la && find . -maxdepth 2' } }
      }),
      toolBlock('t2', 'exec_shell', {
        toolKind: 'command_execution',
        summary: 'exec_shell: git log --oneline -5',
        meta: { tool_input: { command: 'git log --oneline -5' } }
      })
    ]
    const rows = groupProcessRows(blocks)
    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({ type: 'tool_batch', toolName: 'exec_shell' })
    expect(rows[0]!.type === 'tool_batch' && rows[0].blocks).toHaveLength(2)
  })

  it('folds mixed reads and probe shells', () => {
    const blocks: ChatBlock[] = [
      toolBlock('t1', 'read_file'),
      toolBlock('t2', 'exec_shell', {
        toolKind: 'command_execution',
        summary: 'exec_shell: git status -sb',
        meta: { tool_input: { command: 'git status -sb' } }
      }),
      toolBlock('t3', 'read_file')
    ]
    const rows = groupProcessRows(blocks)
    expect(rows).toHaveLength(1)
    expect(rows[0]).toMatchObject({ type: 'tool_batch', toolName: 'probe', mixed: true })
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
      toolBlock('t1', 'agent'),
      toolBlock('t2', 'agent_spawn')
    ]
    const rows = groupProcessRows(blocks)
    expect(rows.every((row) => row.type === 'block')).toBe(true)
  })
})

describe('trailingThinkingIndicatorId', () => {
  it('returns null when the turn is idle', () => {
    const rows = groupProcessRows([
      { kind: 'reasoning', id: 'r1', text: 'done thinking' }
    ])
    expect(trailingThinkingIndicatorId(rows, false)).toBeNull()
  })

  it('keeps the indicator only on the newest trailing thought', () => {
    const rows = groupProcessRows([
      { kind: 'reasoning', id: 'r1', text: 'first' },
      {
        kind: 'assistant',
        id: 'p1',
        text: '获取百度热搜页面。',
        agentSegment: 'mid_turn_preface'
      },
      {
        kind: 'tool',
        id: 't1',
        summary: 'fetch',
        status: 'success',
        toolKind: 'tool_call'
      },
      { kind: 'reasoning', id: 'r2', text: 'second' },
      {
        kind: 'assistant',
        id: 'p2',
        text: '换 JSON 接口。',
        agentSegment: 'mid_turn_preface'
      }
    ])
    expect(trailingThinkingIndicatorId(rows, true)).toBe('p2')
  })

  it('clears the indicator once a tool follows the previous thought', () => {
    const rows = groupProcessRows([
      {
        kind: 'assistant',
        id: 'p1',
        text: '获取百度热搜页面。',
        agentSegment: 'mid_turn_preface'
      },
      {
        kind: 'tool',
        id: 't1',
        summary: 'fetch',
        status: 'running',
        toolKind: 'tool_call'
      }
    ])
    expect(trailingThinkingIndicatorId(rows, true)).toBeNull()
  })
})

describe('planProcessRenderChunks', () => {
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

  it('leaves every row expanded when the turn is settled', () => {
    const rows = groupProcessRows([
      toolBlock('t1', 'read_file'),
      toolBlock('t2', 'read_file'),
      { kind: 'assistant', id: 'p1', text: 'next', agentSegment: 'mid_turn_preface' },
      toolBlock('t3', 'read_file'),
      toolBlock('t4', 'read_file')
    ])
    const chunks = planProcessRenderChunks(rows, false)
    expect(chunks.every((chunk) => chunk.type === 'row')).toBe(true)
    expect(chunks).toHaveLength(3)
  })

  it('folds an older probe run once a later work row is the live tail', () => {
    const rows = groupProcessRows([
      toolBlock('t1', 'read_file'),
      toolBlock('t2', 'read_file'),
      { kind: 'assistant', id: 'p1', text: 'next', agentSegment: 'mid_turn_preface' },
      toolBlock('t3', 'read_file'),
      toolBlock('t4', 'read_file')
    ])
    expect(findLastLiveWorkRowId(rows, true)).toBe('batch:t3')
    const chunks = planProcessRenderChunks(rows, true)
    expect(chunks).toHaveLength(3)
    expect(chunks[0]).toMatchObject({ type: 'work_summary', id: 'batch:t1' })
    expect(chunks[0]!.type === 'work_summary' && chunks[0].summary.compose.reads).toBe(2)
    expect(chunks[1]).toMatchObject({ type: 'row' })
    expect(chunks[2]).toMatchObject({ type: 'row' })
  })

  it('does not fold the live tail or a single older tool', () => {
    const rows = groupProcessRows([
      toolBlock('t1', 'write_file', { toolKind: 'file_change' }),
      { kind: 'assistant', id: 'p1', text: 'next', agentSegment: 'mid_turn_preface' },
      toolBlock('t2', 'read_file')
    ])
    const chunks = planProcessRenderChunks(rows, true)
    expect(chunks.every((chunk) => chunk.type === 'row')).toBe(true)
  })

  it('keeps errors and running tools out of the summary', () => {
    const rows = groupProcessRows([
      toolBlock('t1', 'read_file'),
      toolBlock('t2', 'read_file', { status: 'error' }),
      { kind: 'assistant', id: 'p1', text: 'next', agentSegment: 'mid_turn_preface' },
      toolBlock('t3', 'read_file', { status: 'running' })
    ])
    const chunks = planProcessRenderChunks(rows, true)
    expect(chunks.some((chunk) => chunk.type === 'work_summary')).toBe(false)
  })
})

describe('tail-anchor math', () => {
  it('reserves space so a short turn can sit at the top', () => {
    expect(
      computeTailAnchorSpacerPx({
        viewportHeight: 800,
        userHeight: 80,
        contentAfterUser: 0,
        topInset: 16
      })
    ).toBe(704)
  })

  it('shrinks the reserve as the answer grows and hits zero when it fills the viewport', () => {
    expect(
      computeTailAnchorSpacerPx({
        viewportHeight: 800,
        userHeight: 80,
        contentAfterUser: 400,
        topInset: 16
      })
    ).toBe(304)
    expect(
      computeTailAnchorSpacerPx({
        viewportHeight: 800,
        userHeight: 80,
        contentAfterUser: 900,
        topInset: 16
      })
    ).toBe(0)
  })

  it('pins the user bubble just below the top inset', () => {
    expect(computeTailAnchorScrollTop({ userOffsetTop: 1200, topInset: 16 })).toBe(1184)
  })

  it('releases when the user scrolls or the reserve is exhausted', () => {
    expect(shouldReleaseTailAnchor({ spacerPx: 40, userScrolled: true })).toBe(true)
    expect(shouldReleaseTailAnchor({ spacerPx: 4, userScrolled: false })).toBe(true)
    expect(shouldReleaseTailAnchor({ spacerPx: 40, userScrolled: false })).toBe(false)
  })
})

