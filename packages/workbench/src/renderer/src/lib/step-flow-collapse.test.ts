import { describe, expect, it } from 'vitest'
import type { StepFlowItem } from '../components/chat/StepFlow'
import { collapseStepFlowProbes, isMergeableProbeTool } from './step-flow-collapse'
import { timelineToFlowItems } from './task-step-flow'
import { subagentStepsToFlowItems } from './subagent-mailbox'
import type { SubagentStepState } from './subagent-mailbox'

function probe(
  id: string,
  toolName: string,
  detail: string,
  status: StepFlowItem['status'] = 'ok'
): StepFlowItem {
  return {
    id,
    status,
    label: toolName === 'read_file' ? '读取文件' : toolName,
    detail,
    toolName
  }
}

describe('isMergeableProbeTool', () => {
  it('allows read/list/search probes', () => {
    expect(isMergeableProbeTool('read_file')).toBe(true)
    expect(isMergeableProbeTool('list_dir')).toBe(true)
    expect(isMergeableProbeTool('grep')).toBe(true)
  })

  it('rejects shell, writes, and orchestration', () => {
    expect(isMergeableProbeTool('exec_shell')).toBe(false)
    expect(isMergeableProbeTool('write_file')).toBe(false)
    expect(isMergeableProbeTool('agent_spawn')).toBe(false)
  })
})

describe('collapseStepFlowProbes', () => {
  it('folds 8 consecutive successful read_file into one batch', () => {
    const items = Array.from({ length: 8 }, (_, i) =>
      probe(`r${i}`, 'read_file', `…/file${i}.tsx`)
    )
    const collapsed = collapseStepFlowProbes(items)
    expect(collapsed).toHaveLength(1)
    expect(collapsed[0]?.variant).toBe('batch')
    expect(collapsed[0]?.batchCount).toBe(8)
    expect(collapsed[0]?.batchToolName).toBe('read_file')
    expect(collapsed[0]?.output?.split('\n')).toHaveLength(8)
    expect(collapsed[0]?.detail).toBeUndefined()
  })

  it('does not fold a single probe', () => {
    const items = [probe('r0', 'read_file', '…/a.tsx')]
    expect(collapseStepFlowProbes(items)).toEqual(items)
  })

  it('does not fold running probes', () => {
    const items = [
      probe('r0', 'read_file', '…/a.tsx', 'running'),
      probe('r1', 'read_file', '…/b.tsx', 'running')
    ]
    expect(collapseStepFlowProbes(items)).toHaveLength(2)
  })

  it('flushes batch when narration interrupts', () => {
    const items: StepFlowItem[] = [
      probe('r0', 'read_file', '…/a.tsx'),
      probe('r1', 'read_file', '…/b.tsx'),
      {
        id: 'n1',
        status: 'info',
        label: '接下来看审批气泡',
        variant: 'narration'
      },
      probe('r2', 'read_file', '…/c.tsx'),
      probe('r3', 'read_file', '…/d.tsx')
    ]
    const collapsed = collapseStepFlowProbes(items)
    expect(collapsed).toHaveLength(3)
    expect(collapsed[0]?.variant).toBe('batch')
    expect(collapsed[0]?.batchCount).toBe(2)
    expect(collapsed[1]?.variant).toBe('narration')
    expect(collapsed[2]?.variant).toBe('batch')
    expect(collapsed[2]?.batchCount).toBe(2)
  })
})

describe('subagentStepsToFlowItems collapse', () => {
  it('batches consecutive completed reads from mailbox steps', () => {
    const steps: SubagentStepState[] = [
      {
        id: 'p1',
        kind: 'progress',
        label: '先扫一遍 chat 组件',
        output: '先扫一遍 chat 组件'
      },
      ...Array.from({ length: 5 }, (_, i) => ({
        id: `tool-${i}`,
        kind: 'tool' as const,
        toolName: 'read_file',
        ok: true as const,
        label: '读取文件',
        input: JSON.stringify({ path: `packages/workbench/src/chat/f${i}.tsx` })
      }))
    ]
    const items = subagentStepsToFlowItems(steps, 0, 'completed')
    const batches = items.filter((i) => i.variant === 'batch')
    expect(batches).toHaveLength(1)
    expect(batches[0]?.batchCount).toBe(5)
    expect(batches[0]?.depth).toBe(1)
  })
})

describe('timelineToFlowItems collapse', () => {
  it('batches consecutive successful task tools', () => {
    const items = timelineToFlowItems([
      {
        kind: 'tool',
        summary: 'read_file · a.tsx',
        timestamp: null
      },
      {
        kind: 'tool',
        summary: 'read_file · b.tsx',
        timestamp: null
      },
      {
        kind: 'tool',
        summary: 'read_file · c.tsx',
        timestamp: null
      }
    ])
    expect(items).toHaveLength(1)
    expect(items[0]?.variant).toBe('batch')
    expect(items[0]?.batchCount).toBe(3)
  })
})
