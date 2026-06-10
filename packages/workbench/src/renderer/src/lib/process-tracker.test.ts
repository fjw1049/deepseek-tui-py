import { describe, expect, it } from 'vitest'
import type { ChatBlock, GoalStatusPayload } from '../agent/types'
import { buildTrackedProcesses } from './process-tracker'

const goal: NonNullable<GoalStatusPayload['goal']> = {
  goal_id: 'goal_1',
  objective: 'Ship process tracker',
  status: 'active',
  tokens_used: 25,
  token_budget: 100,
  active_seconds: 12
}

function todoBlock(id: string, statuses: string[]): ChatBlock {
  return {
    kind: 'tool',
    id,
    summary: 'checklist_write: items written',
    status: 'success',
    toolKind: 'tool_call',
    meta: {
      tool_name: 'checklist_write',
      task_updates: {
        checklist: {
          items: statuses.map((status, index) => ({
            id: String(index + 1),
            content: `Task ${index + 1}`,
            status
          }))
        }
      }
    }
  }
}

describe('buildTrackedProcesses', () => {
  it('tracks active goal state', () => {
    const processes = buildTrackedProcesses({ blocks: [], goalStatus: goal })

    expect(processes).toEqual([
      expect.objectContaining({
        id: 'goal:goal_1',
        type: 'goal',
        status: 'running',
        title: 'Ship process tracker',
        progressPct: 25
      })
    ])
  })

  it('tracks workflow blocks without exposing subagent blocks', () => {
    const blocks: ChatBlock[] = [
      {
        kind: 'subagent',
        id: 'subagent-1',
        cardKind: 'delegate',
        agentId: 'agent_1',
        agentType: 'general',
        status: 'running'
      },
      {
        kind: 'workflow',
        id: 'workflow-1',
        toolCallId: 'tool_1',
        workflowName: 'Review flow',
        status: 'running',
        snapshot: {
          name: 'Review flow',
          description: '',
          phases: ['scan'],
          current_phase: 'scan',
          logs: [],
          agents: [],
          agent_count: 4,
          running_count: 1,
          done_count: 2,
          error_count: 0
        }
      }
    ]

    const processes = buildTrackedProcesses({ blocks, goalStatus: null })

    expect(processes).toHaveLength(1)
    expect(processes[0]).toEqual(
      expect.objectContaining({
        id: 'workflow:tool_1',
        type: 'workflow',
        status: 'running',
        subtitle: 'scan · 2/4',
        progressPct: 50
      })
    )
  })

  it('does not promote checklist progress into a task card', () => {
    const blocks: ChatBlock[] = [
      { kind: 'user', id: 'u1', text: 'do it' },
      todoBlock('todo-1', ['completed', 'in_progress'])
    ]

    const processes = buildTrackedProcesses({ blocks, goalStatus: null })

    expect(processes).toEqual([])
  })

  it('ignores ordinary tool calls', () => {
    const blocks: ChatBlock[] = [
      {
        kind: 'tool',
        id: 'read-1',
        summary: 'read_file src/app.ts',
        status: 'success',
        toolKind: 'tool_call'
      }
    ]

    expect(buildTrackedProcesses({ blocks, goalStatus: null })).toEqual([])
  })
})
