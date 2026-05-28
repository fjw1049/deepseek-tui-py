import { describe, expect, it } from 'vitest'
import type { ChatBlock } from '../agent/types'
import { buildTodoSessionForTurn } from './extract-todos-from-blocks'

function todoBlock(
  id: string,
  toolName: string,
  items: Array<{ id: string; content: string; status: string }>
): ChatBlock {
  return {
    kind: 'tool',
    id,
    summary: `${toolName}: items written`,
    status: 'success',
    toolKind: 'tool_call',
    meta: {
      tool_name: toolName,
      task_updates: {
        checklist: { items }
      }
    }
  }
}

describe('buildTodoSessionForTurn', () => {
  it('anchors at first write and merges later updates', () => {
    const blocks: ChatBlock[] = [
      { kind: 'tool', id: 'read-1', summary: 'read_file: src/a.py', status: 'success', toolKind: 'tool_call' },
      todoBlock('todo-write', 'checklist_write', [
        { id: '1', content: 'P0: first', status: 'pending' },
        { id: '2', content: 'P1: second', status: 'pending' }
      ]),
      { kind: 'tool', id: 'grep-1', summary: 'grep_files: pattern', status: 'success', toolKind: 'tool_call' },
      todoBlock('todo-update', 'checklist_update', [
        { id: '1', content: 'P0: first', status: 'completed' },
        { id: '2', content: 'P1: second', status: 'in_progress' }
      ])
    ]

    const session = buildTodoSessionForTurn(blocks)
    expect(session).not.toBeNull()
    expect(session?.anchorBlockId).toBe('todo-write')
    expect(session?.todoBlockIds).toEqual(['todo-write', 'todo-update'])
    expect(session?.items[0]?.status).toBe('completed')
    expect(session?.items[1]?.status).toBe('in_progress')
    expect(session?.isComplete).toBe(false)
  })

  it('marks complete when every item is done', () => {
    const blocks: ChatBlock[] = [
      todoBlock('todo-write', 'todo_write', [
        { id: '1', content: 'A', status: 'completed' },
        { id: '2', content: 'B', status: 'completed' }
      ])
    ]

    const session = buildTodoSessionForTurn(blocks)
    expect(session?.isComplete).toBe(true)
    expect(session?.completionPct).toBe(100)
  })

  it('replaces list on a second write in the same turn', () => {
    const blocks: ChatBlock[] = [
      todoBlock('todo-write-1', 'checklist_write', [
        { id: '1', content: 'Old task', status: 'pending' }
      ]),
      todoBlock('todo-write-2', 'checklist_write', [
        { id: '1', content: 'New task A', status: 'pending' },
        { id: '2', content: 'New task B', status: 'pending' }
      ])
    ]

    const session = buildTodoSessionForTurn(blocks)
    expect(session?.anchorBlockId).toBe('todo-write-1')
    expect(session?.items).toHaveLength(2)
    expect(session?.items[0]?.content).toBe('New task A')
  })
})
