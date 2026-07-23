import { describe, expect, it } from 'vitest'
import type { StepFlowItem } from '../components/chat/StepFlow'
import {
  batchStatus,
  buildProbeBatchMeta,
  collapseStepFlowProbes,
  formatProbeComposeTitleSegment,
  isMergeableProbeTool,
  probeComposeSegments,
  probeComposeTitleIsFullyConcrete,
  probeComposeTitleSegments,
  probeToolKind
} from './step-flow-collapse'
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

describe('probeToolKind / compose', () => {
  it('classifies probe tools', () => {
    expect(probeToolKind('read_file')).toBe('read')
    expect(probeToolKind('search_files')).toBe('search')
    expect(probeToolKind('list_dir')).toBe('list')
    expect(probeToolKind('grep')).toBe('grep')
  })

  it('builds compose segments in stable order', () => {
    const { compose, entries, preview } = buildProbeBatchMeta([
      { toolName: 'read_file', detail: 'a.py' },
      { toolName: 'search_files', detail: 'foo' },
      { toolName: 'read_file', detail: 'b.py' },
      { toolName: 'search_files', detail: 'bar' }
    ])
    expect(compose.reads).toBe(2)
    expect(compose.searches).toBe(2)
    expect(probeComposeSegments(compose).map((s) => s.key)).toEqual([
      'toolBatchComposeRead',
      'toolBatchComposeSearch'
    ])
    expect(entries).toHaveLength(4)
    expect(preview).toBe('a.py · foo · b.py · bar')
  })

  it('uses concrete targets only when each kind appears once', () => {
    const { compose, entries } = buildProbeBatchMeta([
      { toolName: 'read_file', detail: '…/plan.py' },
      { toolName: 'list_dir', detail: '…/model_runners' },
      { toolName: 'grep', detail: 'plan|Plan · apps/routes' }
    ])
    const segments = probeComposeTitleSegments(entries, compose)
    expect(segments).toEqual([
      {
        key: 'toolBatchComposeRead',
        concrete: true,
        target: '…/plan.py',
        count: 1
      },
      {
        key: 'toolBatchComposeList',
        concrete: true,
        target: '…/model_runners',
        count: 1
      },
      {
        key: 'toolBatchComposeGrep',
        concrete: true,
        target: 'plan|Plan · apps/routes',
        count: 1
      }
    ])
    expect(probeComposeTitleIsFullyConcrete(segments)).toBe(true)
  })

  it('keeps count form when a kind appears more than once', () => {
    const { compose, entries } = buildProbeBatchMeta([
      { toolName: 'read_file', detail: 'a.py' },
      { toolName: 'search_files', detail: 'foo' },
      { toolName: 'read_file', detail: 'b.py' }
    ])
    const segments = probeComposeTitleSegments(entries, compose)
    expect(segments).toEqual([
      { key: 'toolBatchComposeRead', concrete: false, target: '', count: 2 },
      { key: 'toolBatchComposeSearch', concrete: true, target: 'foo', count: 1 }
    ])
    expect(probeComposeTitleIsFullyConcrete(segments)).toBe(false)
    const t = (key: string, opts?: Record<string, unknown>) => {
      if (key === 'toolBatchComposeReadCount') return `读 ${opts?.count} 项`
      if (key === 'toolBatchComposeSearch') return `搜 ${opts?.target}`
      return key
    }
    expect(segments.map((seg) => formatProbeComposeTitleSegment(seg, t)).join(' · ')).toBe(
      '读 2 项 · 搜 foo'
    )
  })

  it('falls back to counts when a singleton kind has no target', () => {
    const { compose, entries } = buildProbeBatchMeta([
      { toolName: 'read_file', label: '读取文件' },
      { toolName: 'list_dir', label: '列出目录' }
    ])
    const segments = probeComposeTitleSegments(entries, compose)
    expect(segments).toEqual([
      { key: 'toolBatchComposeRead', concrete: false, target: '', count: 1 },
      { key: 'toolBatchComposeList', concrete: false, target: '', count: 1 }
    ])
    expect(probeComposeTitleIsFullyConcrete(segments)).toBe(false)
  })

  it('never uses humanized tool title as target/preview', () => {
    const meta = buildProbeBatchMeta([
      { toolName: 'read_file', label: '读取文件' },
      { toolName: 'search_files', label: '搜索文件' }
    ])
    expect(meta.preview).toBe('')
    expect(meta.entries.every((e) => e.target === '')).toBe(true)
  })
})

describe('batchStatus', () => {
  it('keeps mostly-successful streaks ok when one row is residual cancelled', () => {
    expect(
      batchStatus([
        probe('a', 'read_file', 'a.py', 'ok'),
        probe('b', 'read_file', 'b.py', 'cancelled'),
        probe('c', 'read_file', 'c.py', 'ok')
      ])
    ).toBe('ok')
  })

  it('marks all-cancelled streaks cancelled', () => {
    expect(
      batchStatus([
        probe('a', 'read_file', 'a.py', 'cancelled'),
        probe('b', 'read_file', 'b.py', 'cancelled')
      ])
    ).toBe('cancelled')
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
    expect(collapsed[0]?.batchMixed).toBe(false)
    expect(collapsed[0]?.batchCompose?.reads).toBe(8)
    expect(collapsed[0]?.batchEntries).toHaveLength(8)
    expect(collapsed[0]?.detail?.split(' · ')).toHaveLength(8)
  })

  it('does not fold a single probe', () => {
    const items = [probe('r0', 'read_file', '…/a.tsx')]
    expect(collapseStepFlowProbes(items)).toEqual(items)
  })

  it('folds consecutive running probes into a live batch', () => {
    const items = [
      probe('r0', 'read_file', '…/a.tsx', 'running'),
      probe('r1', 'read_file', '…/b.tsx', 'running')
    ]
    const collapsed = collapseStepFlowProbes(items)
    expect(collapsed).toHaveLength(1)
    expect(collapsed[0]?.variant).toBe('batch')
    expect(collapsed[0]?.status).toBe('running')
    expect(collapsed[0]?.batchCount).toBe(2)
  })

  it('omits missing targets from preview instead of echoing tool titles', () => {
    const items: StepFlowItem[] = [
      { id: '1', status: 'running', label: '读取文件', toolName: 'read_file' },
      { id: '2', status: 'running', label: '搜索文件', toolName: 'search_files' }
    ]
    const collapsed = collapseStepFlowProbes(items)
    expect(collapsed[0]?.detail).toBeUndefined()
    expect(collapsed[0]?.batchEntries?.map((e) => e.target)).toEqual(['', ''])
  })

  it('folds consecutive failed probes of the same tool', () => {
    const items = [
      probe('r0', 'read_file', '…/a.py', 'failed'),
      probe('r1', 'read_file', '…/a.py', 'failed'),
      probe('r2', 'read_file', '…/a.py', 'failed'),
      probe('r3', 'read_file', '…/a.py', 'failed')
    ]
    const collapsed = collapseStepFlowProbes(items)
    expect(collapsed).toHaveLength(1)
    expect(collapsed[0]?.variant).toBe('batch')
    expect(collapsed[0]?.batchCount).toBe(4)
    expect(collapsed[0]?.status).toBe('failed')
  })

  it('folds mixed consecutive read/search probes with compose counts', () => {
    const items = [
      probe('r0', 'read_file', '…/scheduler.py'),
      probe('s0', 'search_files', 'run_workflow'),
      probe('r1', 'read_file', '…/runtime.py'),
      probe('s1', 'search_files', '_collect_errors')
    ]
    const collapsed = collapseStepFlowProbes(items)
    expect(collapsed).toHaveLength(1)
    expect(collapsed[0]?.variant).toBe('batch')
    expect(collapsed[0]?.batchCount).toBe(4)
    expect(collapsed[0]?.batchMixed).toBe(true)
    expect(collapsed[0]?.batchToolName).toBe('probe')
    expect(collapsed[0]?.batchCompose).toEqual({
      reads: 2,
      searches: 2,
      lists: 0,
      greps: 0,
      webs: 0,
      others: 0
    })
    expect(collapsed[0]?.batchEntries?.[0]).toMatchObject({
      kind: 'read',
      target: '…/scheduler.py'
    })
    expect(collapsed[0]?.batchEntries?.[1]).toMatchObject({
      kind: 'search',
      target: 'run_workflow'
    })
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

  it('batches alternating read/search under a narration', () => {
    const steps: SubagentStepState[] = [
      {
        id: 'p1',
        kind: 'progress',
        label: 'look at remaining scheduler code',
        output: 'look at remaining scheduler code'
      },
      {
        id: 't1',
        kind: 'tool',
        toolName: 'read_file',
        ok: true,
        label: '读取文件',
        input: 'scheduler.py'
      },
      {
        id: 't2',
        kind: 'tool',
        toolName: 'search_files',
        ok: true,
        label: '搜索文件',
        input: 'run_workflow'
      },
      {
        id: 't3',
        kind: 'tool',
        toolName: 'read_file',
        ok: true,
        label: '读取文件',
        input: 'runtime.py'
      },
      {
        id: 't4',
        kind: 'tool',
        toolName: 'search_files',
        ok: true,
        label: '搜索文件',
        input: '_collect_errors'
      }
    ]
    const items = subagentStepsToFlowItems(steps, 0, 'running')
    expect(items.filter((i) => i.variant === 'narration')).toHaveLength(1)
    const batches = items.filter((i) => i.variant === 'batch')
    expect(batches).toHaveLength(1)
    expect(batches[0]?.batchCount).toBe(4)
    expect(batches[0]?.batchMixed).toBe(true)
    expect(batches[0]?.batchCompose?.reads).toBe(2)
    expect(batches[0]?.batchCompose?.searches).toBe(2)
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

  it('batches mixed read/search task tools with compose', () => {
    const items = timelineToFlowItems([
      { kind: 'tool', summary: 'read_file · a.py', timestamp: null },
      { kind: 'tool', summary: 'search_files · foo', timestamp: null },
      { kind: 'tool', summary: 'read_file · b.py', timestamp: null }
    ])
    expect(items).toHaveLength(1)
    expect(items[0]?.variant).toBe('batch')
    expect(items[0]?.batchMixed).toBe(true)
    expect(items[0]?.batchCount).toBe(3)
    expect(items[0]?.batchCompose?.reads).toBe(2)
    expect(items[0]?.batchCompose?.searches).toBe(1)
  })
})
