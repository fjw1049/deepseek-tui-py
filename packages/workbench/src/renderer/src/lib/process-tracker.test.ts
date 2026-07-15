import { describe, expect, it } from 'vitest'
import type { ChatBlock } from '../agent/types'
import { buildTrackedProcesses } from './process-tracker'

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

    const processes = buildTrackedProcesses({ blocks })

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

    const processes = buildTrackedProcesses({ blocks })

    expect(processes).toEqual([])
  })

  it('collapses cancelled + running for the same runId into one running card', () => {
    const snap = {
      name: 'repo_review',
      description: '',
      phases: ['plan', 'inspect'],
      current_phase: 'Inspect',
      logs: [],
      agents: [],
      agent_count: 2,
      running_count: 1,
      done_count: 1,
      error_count: 0
    }
    const blocks: ChatBlock[] = [
      {
        kind: 'workflow',
        id: 'old',
        toolCallId: 'tool_old',
        workflowName: 'repo_review',
        status: 'cancelled',
        runId: 'wf_abc',
        snapshot: { ...snap, running_count: 0, done_count: 1 }
      },
      {
        kind: 'workflow',
        id: 'new',
        toolCallId: 'tool_new',
        workflowName: 'repo_review',
        status: 'running',
        runId: 'wf_abc',
        snapshot: snap
      }
    ]

    const processes = buildTrackedProcesses({ blocks })
    expect(processes).toHaveLength(1)
    expect(processes[0]?.status).toBe('running')
    expect(processes[0]?.id).toBe('workflow:tool_new')
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

    expect(buildTrackedProcesses({ blocks })).toEqual([])
  })
})
