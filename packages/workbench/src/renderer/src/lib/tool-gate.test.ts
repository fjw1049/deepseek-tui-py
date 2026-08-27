import { describe, expect, it } from 'vitest'

import type { ChatBlock, ToolBlock } from '../agent/types'
import { findPendingToolGate, hasPendingToolGate, toolGateIds } from './tool-gate'

function tool(overrides: Partial<ToolBlock> = {}): ToolBlock {
  return {
    kind: 'tool',
    id: 'item_cmd',
    summary: 'exec_shell: ls',
    status: 'running',
    toolKind: 'command_execution',
    meta: { tool_call_id: 'call_1' },
    ...overrides
  }
}

describe('toolGateIds', () => {
  it('includes the item id and meta.tool_call_id', () => {
    expect(toolGateIds(tool())).toEqual(['item_cmd', 'call_1'])
  })
})

describe('findPendingToolGate', () => {
  it('matches approval and elevation by tool_call_id', () => {
    const blocks: ChatBlock[] = [
      tool(),
      {
        kind: 'approval',
        id: 'approval-call_1',
        approvalId: 'call_1',
        summary: 'Shell command requested',
        status: 'pending'
      },
      {
        kind: 'elevation',
        id: 'elevation-call_1',
        elevationId: 'call_1',
        reason: 'Sandbox blocked',
        elevationKind: 'full_access',
        status: 'pending'
      }
    ]
    const gate = findPendingToolGate(blocks, tool())
    expect(gate.approval?.approvalId).toBe('call_1')
    expect(gate.elevation?.elevationId).toBe('call_1')
    expect(hasPendingToolGate(gate)).toBe(true)
  })

  it('ignores resolved gates and other tool calls', () => {
    const blocks: ChatBlock[] = [
      {
        kind: 'approval',
        id: 'approval-call_1',
        approvalId: 'call_1',
        summary: 'done',
        status: 'allowed'
      },
      {
        kind: 'approval',
        id: 'approval-other',
        approvalId: 'call_other',
        summary: 'other',
        status: 'pending'
      }
    ]
    expect(findPendingToolGate(blocks, tool())).toEqual({ approval: null, elevation: null })
  })
})
