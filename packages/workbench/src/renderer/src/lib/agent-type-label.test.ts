import { describe, expect, it } from 'vitest'
import { humanizeAgentType } from './agent-type-label'
import { countSubagentRailSteps } from '../components/chat/MessageTimeline'
import type { StepFlowItem } from '../components/chat/StepFlow'

describe('humanizeAgentType', () => {
  it('maps known types to Chinese labels', () => {
    expect(humanizeAgentType('explore')).toBe('探索')
    expect(humanizeAgentType('general')).toBe('通用')
  })

  it('passes through unknown types', () => {
    expect(humanizeAgentType('custom-agent')).toBe('custom-agent')
  })
})

describe('countSubagentRailSteps', () => {
  it('counts tools and batches, skips narration', () => {
    const items: StepFlowItem[] = [
      { id: 'n', status: 'info', label: '先看结构', variant: 'narration' },
      {
        id: 'b',
        status: 'ok',
        label: '读取文件',
        variant: 'batch',
        batchCount: 8,
        batchToolName: 'read_file'
      },
      {
        id: 't',
        status: 'ok',
        label: '浏览目录',
        toolName: 'list_dir',
        detail: '…/chat'
      },
      { id: 's', status: 'running', label: '● running' }
    ]
    expect(countSubagentRailSteps(items)).toBe(2)
  })
})
