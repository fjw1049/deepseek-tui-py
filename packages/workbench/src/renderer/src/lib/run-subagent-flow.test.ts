import { describe, expect, it } from 'vitest'
import { buildSubagentTreeNodes, resolveSubagentFlowItems, type SubagentBlock } from './run-subagent-flow'

const root: SubagentBlock = {
  kind: 'subagent', id: 'root', agentId: 'root', agentType: 'fanout', cardKind: 'fanout',
  status: 'running', workers: [{ id: 'one', status: 'completed' }, { id: 'two', status: 'running' }],
  workerSteps: {
    one: [{ id: 'tool-one', kind: 'tool', toolName: 'read_file', label: 'Read one', ok: null }],
    two: [{ id: 'tool-two', kind: 'tool', toolName: 'read_file', label: 'Read two', ok: null }]
  }
}
describe('subagent run selection', () => {
  it('shows only the selected worker and uses its terminal status', () => {
    const one = resolveSubagentFlowItems(root, [root], 'one')
    expect(one).toHaveLength(1)
    expect(one[0].id).toContain('tool-one')
    expect(JSON.stringify(one)).not.toContain('tool-two')
    expect(one[0].status).not.toBe('running')
    expect(resolveSubagentFlowItems(root, [root], 'two')[0].status).toBe('running')
  })
  it('handles nested child relationships without looping', () => {
    const parent = { ...root, childIds: ['child'] }
    const child: SubagentBlock = { kind: 'subagent', id: 'child', agentId: 'child', agentType: 'code', cardKind: 'delegate', status: 'running', childIds: ['root'] }
    expect(buildSubagentTreeNodes(parent, [parent, child]).map((node) => node.id)).toEqual(['root', 'one', 'two', 'child'])
  })
})
