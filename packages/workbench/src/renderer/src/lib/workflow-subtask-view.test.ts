import { describe, expect, it } from 'vitest'
import type { WorkflowSnapshotPayload } from './workflow-snapshot'
import {
  isOpaqueSubtaskLabel,
  isWorkflowShellLabel,
  resolveSubtaskTitle,
  workflowFocusSubtask,
  workflowGoalText,
  workflowSubtaskProgress,
  workflowSubtasks
} from './workflow-subtask-view'

function snap(partial: Partial<WorkflowSnapshotPayload>): WorkflowSnapshotPayload {
  return {
    name: 'adaptive',
    description: '',
    phases: [],
    logs: [],
    agents: [],
    agent_count: 0,
    running_count: 0,
    done_count: 0,
    error_count: 0,
    ...partial
  }
}

describe('workflowGoalText', () => {
  it('prefers task description over preset name', () => {
    expect(
      workflowGoalText(
        snap({ description: '深入研究整个项目', name: 'adaptive' }),
        'adaptive'
      )
    ).toBe('深入研究整个项目')
  })

  it('falls back to workflow name when description is shell-like', () => {
    expect(workflowGoalText(snap({ description: 'adaptive', name: 'adaptive' }), 'repo_review')).toBe(
      'repo_review'
    )
  })
})

describe('workflowSubtasks', () => {
  it('keeps workers with agent_id and readable labels', () => {
    const tasks = workflowSubtasks(
      snap({
        agents: [
          {
            step_id: 'orchestrate',
            label: 'orchestrate',
            phase_id: 'p',
            status: 'running'
          },
          {
            step_id: 's1',
            label: '扫描 workbench',
            phase_id: 'p',
            status: 'running',
            agent_id: 'ag-1'
          },
          {
            step_id: 's2',
            label: 'dynamic:orchestrate:r1',
            phase_id: 'p',
            status: 'queued',
            agent_id: 'ag-2'
          },
          {
            step_id: 's3',
            label: '整理结论',
            phase_id: 'p',
            status: 'done',
            agent_id: 'ag-3'
          }
        ]
      })
    )
    expect(tasks.map((t) => t.label)).toEqual(['扫描 workbench', '整理结论'])
    expect(tasks[0]?.status).toBe('running')
  })
})

describe('workflowFocusSubtask', () => {
  it('prefers running then error then queued', () => {
    const tasks = workflowSubtasks(
      snap({
        agents: [
          {
            step_id: 'a',
            label: 'queued work',
            phase_id: 'p',
            status: 'queued',
            agent_id: '1'
          },
          {
            step_id: 'b',
            label: 'failed work',
            phase_id: 'p',
            status: 'error',
            agent_id: '2'
          },
          {
            step_id: 'c',
            label: 'active work',
            phase_id: 'p',
            status: 'running',
            agent_id: '3'
          }
        ]
      })
    )
    expect(workflowFocusSubtask(tasks)?.label).toBe('active work')
  })
})

describe('workflowSubtaskProgress', () => {
  it('counts done and skipped against total subtasks', () => {
    const tasks = workflowSubtasks(
      snap({
        agents: [
          {
            step_id: 'a',
            label: 'one',
            phase_id: 'p',
            status: 'done',
            agent_id: '1'
          },
          {
            step_id: 'b',
            label: 'two',
            phase_id: 'p',
            status: 'skipped',
            agent_id: '2'
          },
          {
            step_id: 'c',
            label: 'three',
            phase_id: 'p',
            status: 'running',
            agent_id: '3'
          }
        ]
      })
    )
    expect(workflowSubtaskProgress(tasks)).toEqual({ done: 2, total: 3 })
  })
})

describe('isWorkflowShellLabel', () => {
  it('detects engine chrome labels', () => {
    expect(isWorkflowShellLabel('orchestrate')).toBe(true)
    expect(isWorkflowShellLabel('dynamic:orchestrate:r2')).toBe(true)
    expect(isWorkflowShellLabel('扫描 packages')).toBe(false)
  })
})

describe('resolveSubtaskTitle', () => {
  it('uses spawn prompt when label is an opaque id', () => {
    expect(
      resolveSubtaskTitle(
        { label: 'a_engine', resultPreview: null, error: null },
        '梳理 engine/orchestrator 的调度与事件流'
      )
    ).toBe('梳理 engine/orchestrator 的调度与事件流')
  })

  it('keeps human-readable labels', () => {
    expect(
      resolveSubtaskTitle(
        { label: 'Electron GUI 路径端到端数据流', resultPreview: null, error: null },
        'some longer prompt ignored'
      )
    ).toBe('Electron GUI 路径端到端数据流')
  })

  it('detects opaque snake_case ids', () => {
    expect(isOpaqueSubtaskLabel('a_engine')).toBe(true)
    expect(isOpaqueSubtaskLabel('a_config_state')).toBe(true)
    expect(isOpaqueSubtaskLabel('Electron workbench 前端')).toBe(false)
  })
})
