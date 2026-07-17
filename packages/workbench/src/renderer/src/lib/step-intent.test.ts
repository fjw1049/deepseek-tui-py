import { describe, expect, it } from 'vitest'
import { buildStepIntent } from './step-intent'
import { timelineToFlowItems } from './task-step-flow'

describe('buildStepIntent', () => {
  it('humanizes tool name and extracts path from input_summary JSON', () => {
    const intent = buildStepIntent({
      toolName: 'read_file',
      inputSummary: '{"path":"packages/workbench/src/components/chat/StepFlow.tsx"}'
    })
    expect(intent.title).toBe('读取文件')
    expect(intent.detail).toContain('StepFlow.tsx')
    expect(intent.label).toContain('读取文件')
    expect(intent.label).toContain('StepFlow.tsx')
  })

  it('describes list_dir targets', () => {
    const intent = buildStepIntent({
      toolName: 'list_dir',
      inputSummary: '{"path":"packages/workbench/src/components/chat"}'
    })
    expect(intent.title).toBe('浏览目录')
    expect(intent.detail).toContain('chat')
  })

  it('uses task primaryArg when summary is name · arg', () => {
    const intent = buildStepIntent({
      toolName: 'grep',
      primaryArg: 'StepFlow · packages/workbench'
    })
    expect(intent.title).toBe('搜索代码')
    expect(intent.detail.length).toBeGreaterThan(0)
  })
})

describe('timelineToFlowItems', () => {
  it('puts intent on the rail instead of step N · tool · ok', () => {
    const items = timelineToFlowItems([
      {
        kind: 'tool',
        summary: 'read_file · packages/workbench/src/foo.ts',
        timestamp: '2026-07-17T10:00:00.000Z'
      }
    ])
    expect(items).toHaveLength(1)
    expect(items[0]?.label).toBe('读取文件')
    expect(items[0]?.detail).toContain('foo.ts')
    expect(items[0]?.label).not.toMatch(/step \d/)
    expect(items[0]?.input).toContain('foo.ts')
  })
})
