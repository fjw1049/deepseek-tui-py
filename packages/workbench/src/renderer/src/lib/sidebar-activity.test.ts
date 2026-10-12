import { describe, expect, it } from 'vitest'
import type { NormalizedThread } from '../agent/types'
import { activityDismissalKey, buildSidebarActivity, filterDismissedActivity } from './sidebar-activity'

const thread = (id: string, extra: Partial<NormalizedThread> = {}): NormalizedThread => ({
  id, title: id, model: 'deepseek', mode: 'agent', workspace: '/projects/app',
  createdAt: '2026-10-10T00:00:00Z', updatedAt: '2026-10-10T00:00:00Z', ...extra
})
const build = (threads: NormalizedThread[], extra: Partial<Parameters<typeof buildSidebarActivity>[0]> & { dismissed?: Record<string, string> } = {}) =>
  filterDismissedActivity(buildSidebarActivity({ threads, hiddenWorkspacePaths: [], runningIds: new Set(), unreadThreadIds: {}, activeThreadId: null, activeWaiting: false, ...extra }), extra.dismissed ?? {})

describe('sidebar activity', () => {
  it('lists waiting, failed, running and unread across projects without duplicates', () => {
    const rows = build([
      thread('waiting', { activityWaiting: true, latestTurnStatus: 'in_progress' }),
      thread('failed', { latestTurnStatus: 'failed' }),
      thread('running', { workspace: '/projects/other', latestTurnStatus: 'in_progress' }),
      thread('done'), thread('idle')
    ], { unreadThreadIds: { failed: true, running: true, done: true } })
    expect(rows.filter((r) => r.status === 'waiting' || r.status === 'failed').map((r) => r.thread.id)).toEqual(['failed', 'waiting'])
    expect(rows.filter((r) => r.status === 'running').map((r) => [r.thread.id, r.unread])).toEqual([['running', true]])
    expect(rows.filter((r) => r.status === 'unread').map((r) => r.thread.id)).toEqual(['done'])
    expect(rows).toHaveLength(5)
  })
  it('keeps a read failure actionable, but lets a live retry supersede it', () => {
    expect(build([thread('retry', { latestTurnFailed: true })])[0].status).toBe('failed')
    const rows = build([thread('retry', { latestTurnFailed: true })], { runningIds: new Set(['retry']) })
    expect(rows.filter((r) => r.status === 'waiting' || r.status === 'failed')).toHaveLength(0)
    expect(rows.filter((r) => r.status === 'running')).toHaveLength(1)
  })
  it('excludes archived and hidden projects and suppresses active unread', () => {
    const rows = build([thread('archive', { archived: true }), thread('hidden', { workspace: '/hidden' }), thread('active')], {
      hiddenWorkspacePaths: ['/hidden'], activeThreadId: 'active', unreadThreadIds: { archive: true, hidden: true, active: true }
    })
    expect(rows.map((r) => [r.thread.id, r.unread])).toEqual([['active', false]])
  })
  it('uses pending input in the active transcript ahead of running state', () => {
    const rows = build([thread('active')], { activeThreadId: 'active', activeWaiting: true, runningIds: new Set(['active']) })
    expect(rows.filter((r) => r.status === 'waiting' || r.status === 'failed')[0].status).toBe('waiting')
    expect(rows.filter((r) => r.status === 'running')).toHaveLength(0)
  })
  it('does not reorder rows on background timestamp updates', () => {
    const rows = [thread('a'), thread('b')]
    const before = build(rows, { runningIds: new Set(['a', 'b']) }).map((r) => r.thread.id)
    rows[1].updatedAt = '2026-10-11T00:00:00Z'
    expect(build(rows.reverse(), { runningIds: new Set(['a', 'b']) }).map((r) => r.thread.id)).toEqual(before)
  })
})

it('remembers only the dismissed turn/status, without changing the conversation or unread state', () => {
  const original = thread('failed', { latestTurnId: 'turn-1', latestTurnStatus: 'failed' })
  const row = build([original])[0]
  const dismissed = { failed: activityDismissalKey(row) }
  const unreadThreadIds = { failed: true }
  expect(build([original], { dismissed, unreadThreadIds })).toHaveLength(0)
  expect(build([{ ...original, updatedAt: '2026-10-12' }], { dismissed })).toHaveLength(0)
  expect(build([{ ...original, latestTurnId: 'turn-2' }], { dismissed })).toHaveLength(1)
  expect(build([original], { dismissed, runningIds: new Set(['failed']) })[0].status).toBe('running')
  expect(original.archived).toBeUndefined()
  expect(unreadThreadIds.failed).toBe(true)
})

it('sorts all sessions by recent activity, including read and idle sessions ahead of running ones', () => {
  const rows = build([
    thread('running', { latestTurnStatus: 'in_progress', activityAt: '2026-10-10T01:00:00Z' }),
    thread('idle', { workspace: '/other', createdAt: '2026-10-12T00:00:00Z' }),
    thread('done', { latestTurnStatus: 'completed', activityAt: '2026-10-11T00:00:00Z' })
  ])
  expect(rows.map((r) => [r.thread.id, r.status])).toEqual([
    ['idle', 'idle'], ['done', 'completed'], ['running', 'running']
  ])
  expect(build([{ ...rows[2].thread, activityAt: '2026-10-13T00:00:00Z' }, rows[0].thread])[0].thread.id).toBe('running')
})

it('preserves queued, conflict and stopped indicators with independent unread marks', () => {
  const rows = build([
    thread('queued', { latestTurnStatus: 'queued' }),
    thread('conflict', { publishBlocked: true }),
    thread('interrupted', { latestTurnStatus: 'interrupted' }),
    thread('canceled', { latestTurnStatus: 'canceled' })
  ], { unreadThreadIds: { canceled: true } })
  expect(Object.fromEntries(rows.map((r) => [r.thread.id, r.status]))).toEqual({
    queued: 'running', conflict: 'failed', interrupted: 'stopped', canceled: 'stopped'
  })
  expect(rows.find((r) => r.thread.id === 'canceled')?.unread).toBe(true)
})
