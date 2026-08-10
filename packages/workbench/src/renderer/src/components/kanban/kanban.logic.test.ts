import { describe, expect, it } from 'vitest'
import {
  buildKanbanBoard,
  deriveKanbanColumn,
  overviewVisibleCards,
  reorderDraftCardIds,
  OVERVIEW_RENDER_CAP,
  type KanbanProjectBoard
} from './kanban.logic'
import type { NormalizedThread } from '../../agent/types'

function thread(partial: Partial<NormalizedThread> & Pick<NormalizedThread, 'id'>): NormalizedThread {
  return {
    title: partial.title ?? 'Task',
    updatedAt: partial.updatedAt ?? '2026-08-10T00:00:00.000Z',
    model: partial.model ?? 'deepseek',
    mode: partial.mode ?? 'agent',
    workspace: partial.workspace,
    status: partial.status,
    archived: partial.archived,
    createdAt: partial.createdAt,
    id: partial.id
  }
}

describe('deriveKanbanColumn', () => {
  it('marks running and watched threads as in progress', () => {
    expect(deriveKanbanColumn(thread({ id: 'a', status: 'running' }), new Set())).toBe('inProgress')
    expect(deriveKanbanColumn(thread({ id: 'b', status: 'idle' }), new Set(['b']))).toBe(
      'inProgress'
    )
  })

  it('marks parked prompts as draft even when idle', () => {
    expect(
      deriveKanbanColumn(thread({ id: 'a', status: 'idle', title: 'Old' }), new Set(), {
        draftPrompt: 'follow up'
      })
    ).toBe('draft')
  })

  it('marks completed/idle as done', () => {
    expect(deriveKanbanColumn(thread({ id: 'a', status: 'completed' }), new Set())).toBe('done')
    expect(deriveKanbanColumn(thread({ id: 'b', status: 'idle', title: 'Real title' }), new Set())).toBe(
      'done'
    )
  })

  it('marks only empty unused threads as draft; real chats default to done', () => {
    expect(deriveKanbanColumn(thread({ id: 'a', title: 'New Thread' }), new Set())).toBe('draft')
    expect(deriveKanbanColumn(thread({ id: 'b', title: 'Hello' }), new Set())).toBe('done')
    expect(
      deriveKanbanColumn(thread({ id: 'c', title: 'Fix login bug', status: undefined }), new Set())
    ).toBe('done')
  })
})

describe('buildKanbanBoard', () => {
  it('groups by workspace into column buckets', () => {
    const board = buildKanbanBoard({
      threads: [
        thread({
          id: '1',
          title: 'One',
          workspace: '/Users/me/robotgo',
          status: 'completed',
          updatedAt: '2026-08-10T02:00:00.000Z'
        }),
        thread({
          id: '2',
          title: 'Two',
          workspace: '/Users/me/robotgo',
          status: 'idle',
          updatedAt: '2026-08-10T01:00:00.000Z'
        }),
        thread({
          id: '3',
          title: 'Hidden',
          workspace: '/Users/me/secret',
          status: 'completed'
        }),
        thread({
          id: '4',
          title: 'Chatty',
          workspace: '',
          status: 'completed'
        })
      ],
      hiddenWorkspacePaths: ['/Users/me/secret'],
      projectOrder: [],
      projectSortMode: 'name_asc',
      inProgressThreadIds: new Set(),
      chatsColumnName: 'Chats'
    })

    expect(board.projects.map((p) => p.projectName)).toEqual(['robotgo', 'Chats'])
    expect(board.totalCount).toBe(3)
    expect(board.projects[0]?.done.map((c) => c.threadId)).toEqual(['1', '2'])
  })

  it('applies manual draft order', () => {
    const board = buildKanbanBoard({
      threads: [
        thread({ id: 'a', title: 'New Thread', workspace: '/p', updatedAt: '2026-08-10T03:00:00.000Z' }),
        thread({ id: 'b', title: 'New Thread', workspace: '/p', updatedAt: '2026-08-10T02:00:00.000Z' }),
        thread({ id: 'c', title: 'New Thread', workspace: '/p', updatedAt: '2026-08-10T01:00:00.000Z' })
      ],
      hiddenWorkspacePaths: [],
      projectOrder: [],
      projectSortMode: 'name_asc',
      inProgressThreadIds: new Set(),
      chatsColumnName: 'Chats',
      draftOrderByProjectId: { '/p': ['c', 'a', 'b'] }
    })
    expect(board.projects[0]?.draft.map((card) => card.threadId)).toEqual(['c', 'a', 'b'])
  })

  it('applies manual in-progress and done order', () => {
    const board = buildKanbanBoard({
      threads: [
        thread({ id: 'd1', title: 'Done A', workspace: '/p', updatedAt: '2026-08-10T03:00:00.000Z' }),
        thread({ id: 'd2', title: 'Done B', workspace: '/p', updatedAt: '2026-08-10T02:00:00.000Z' }),
        thread({ id: 'r1', title: 'Run A', workspace: '/p', updatedAt: '2026-08-10T04:00:00.000Z' }),
        thread({ id: 'r2', title: 'Run B', workspace: '/p', updatedAt: '2026-08-10T05:00:00.000Z' })
      ],
      hiddenWorkspacePaths: [],
      projectOrder: [],
      projectSortMode: 'name_asc',
      inProgressThreadIds: new Set(['r1', 'r2']),
      chatsColumnName: 'Chats',
      columnOrderByProjectId: {
        '/p': {
          inProgress: ['r2', 'r1'],
          done: ['d2', 'd1']
        }
      }
    })
    expect(board.projects[0]?.inProgress.map((card) => card.threadId)).toEqual(['r2', 'r1'])
    expect(board.projects[0]?.done.map((card) => card.threadId)).toEqual(['d2', 'd1'])
  })
})

describe('overviewVisibleCards', () => {
  it('caps rendered cards', () => {
    const cards = Array.from({ length: OVERVIEW_RENDER_CAP + 3 }, (_, i) => ({
      cardId: String(i),
      threadId: String(i),
      projectId: '/p',
      column: 'done' as const,
      title: `t${i}`,
      branch: null,
      timestamp: null,
      sortTimestamp: i,
      draftPrompt: ''
    }))
    const project: KanbanProjectBoard = {
      projectId: '/p',
      projectName: 'p',
      workspacePath: '/p',
      draft: [],
      inProgress: [],
      done: cards,
      totalCount: cards.length
    }
    const { visibleCards, hiddenCount } = overviewVisibleCards(project)
    expect(visibleCards).toHaveLength(OVERVIEW_RENDER_CAP)
    expect(hiddenCount).toBe(3)
  })
})

describe('reorderDraftCardIds', () => {
  it('moves an id before another', () => {
    expect(reorderDraftCardIds(['a', 'b', 'c'], 'c', 'a')).toEqual(['c', 'a', 'b'])
  })
})
