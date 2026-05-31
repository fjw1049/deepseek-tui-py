import { describe, expect, it } from 'vitest'
import type { ChatBlock } from '../agent/types'
import {
  buildTodoEventsForTurn,
  buildTodoSessionForTurn,
  extractTodosFromBlocks
} from './extract-todos-from-blocks'

function todoBlock(
  id: string,
  toolName: string,
  items: Array<{ id: string; content: string; status: string }>,
  status: 'success' | 'error' = 'success'
): ChatBlock {
  return {
    kind: 'tool',
    id,
    summary: `${toolName}: items written`,
    status,
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

describe('buildTodoEventsForTurn', () => {
  it('records completed todo transitions after the initial list exists', () => {
    const blocks: ChatBlock[] = [
      todoBlock('todo-write', 'checklist_write', [
        { id: '1', content: 'First task', status: 'pending' },
        { id: '2', content: 'Second task', status: 'pending' }
      ]),
      todoBlock('todo-update-1', 'checklist_update', [
        { id: '1', content: 'First task', status: 'completed' },
        { id: '2', content: 'Second task', status: 'in_progress' }
      ]),
      todoBlock('todo-update-2', 'checklist_update', [
        { id: '1', content: 'First task', status: 'completed' },
        { id: '2', content: 'Second task', status: 'completed' }
      ])
    ]

    const events = buildTodoEventsForTurn(blocks)
    expect(events).toEqual([
      {
        blockId: 'todo-update-1',
        kind: 'completed',
        item: { id: '1', content: 'First task', status: 'completed' },
        done: 1,
        total: 2
      },
      {
        blockId: 'todo-update-2',
        kind: 'completed',
        item: { id: '2', content: 'Second task', status: 'completed' },
        done: 2,
        total: 2
      }
    ])
  })
})

describe('error blocks are ignored', () => {
  it('buildTodoSessionForTurn skips error checklist_write blocks', () => {
    const blocks: ChatBlock[] = [
      todoBlock('good-write', 'checklist_write', [
        { id: '1', content: 'Coordinator task', status: 'in_progress' }
      ]),
      todoBlock('bad-write', 'checklist_write', [
        { id: '1', content: 'Coordinator task', status: 'in_progress' },
        { id: '2', content: 'Bubble sort', status: 'in_progress' },
        { id: '3', content: 'Heap sort', status: 'in_progress' }
      ], 'error')
    ]

    const session = buildTodoSessionForTurn(blocks)
    expect(session).not.toBeNull()
    expect(session?.items).toHaveLength(1)
    expect(session?.items[0]?.content).toBe('Coordinator task')
    expect(session?.todoBlockIds).toEqual(['good-write'])
  })

  it('buildTodoEventsForTurn skips error blocks', () => {
    const blocks: ChatBlock[] = [
      todoBlock('write', 'checklist_write', [
        { id: '1', content: 'Step A', status: 'pending' },
        { id: '2', content: 'Step B', status: 'pending' }
      ]),
      todoBlock('err-update', 'checklist_update', [
        { id: '1', content: 'Step A', status: 'completed' },
        { id: '2', content: 'Step B', status: 'in_progress' }
      ], 'error'),
      todoBlock('ok-update', 'checklist_update', [
        { id: '1', content: 'Step A', status: 'completed' },
        { id: '2', content: 'Step B', status: 'in_progress' }
      ])
    ]

    const events = buildTodoEventsForTurn(blocks)
    expect(events).toHaveLength(1)
    expect(events[0]?.blockId).toBe('ok-update')
  })

  it('extractTodosFromBlocks skips error blocks for sidebar snapshot', () => {
    const blocks: ChatBlock[] = [
      todoBlock('good', 'checklist_write', [
        { id: '1', content: 'Real task', status: 'in_progress' }
      ]),
      todoBlock('bad', 'checklist_write', [
        { id: '1', content: 'Corrupted', status: 'in_progress' },
        { id: '2', content: 'Also corrupted', status: 'in_progress' }
      ], 'error')
    ]

    const snapshot = extractTodosFromBlocks(blocks)
    expect(snapshot).not.toBeNull()
    expect(snapshot?.items).toHaveLength(1)
    expect(snapshot?.items[0]?.content).toBe('Real task')
  })
})
