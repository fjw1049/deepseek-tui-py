import { describe, expect, it } from 'vitest'
import type { NormalizedThread } from '../agent/types'
import { buildSidebarActivity } from './sidebar-activity'

const thread = (id: string, extra: Partial<NormalizedThread> = {}): NormalizedThread => ({
  id, title: id, model: 'deepseek', mode: 'agent', workspace: '/projects/app',
  createdAt: '2026-10-10T00:00:00Z', updatedAt: '2026-10-10T00:00:00Z', ...extra
})
const build = (threads: NormalizedThread[], extra: Partial<Parameters<typeof buildSidebarActivity>[0]> = {}) =>
  buildSidebarActivity({ threads, hiddenWorkspacePaths: [], runningIds: new Set(), unreadThreadIds: {}, activeThreadId: null, activeWaiting: false, ...extra })

describe('sidebar activity', () => {
  it('lists waiting, failed, running and unread across projects without duplicates', () => {
    const groups = build([
      thread('waiting', { activityWaiting: true, latestTurnStatus: 'in_progress' }),
      thread('failed', { latestTurnStatus: 'failed' }),
      thread('running', { workspace: '/projects/other', latestTurnStatus: 'in_progress' }),
      thread('done'), thread('idle')
    ], { unreadThreadIds: { failed: true, running: true, done: true } })
    expect(groups.attention.map((r) => r.thread.id)).toEqual(['failed', 'waiting'])
    expect(groups.running.map((r) => [r.thread.id, r.unread])).toEqual([['running', true]])
    expect(groups.unread.map((r) => r.thread.id)).toEqual(['done'])
    expect(Object.values(groups).flat()).toHaveLength(4)
  })
  it('keeps a read failure actionable, but lets a live retry supersede it', () => {
    expect(build([thread('retry', { latestTurnFailed: true })]).attention).toHaveLength(1)
    const groups = build([thread('retry', { latestTurnFailed: true })], { runningIds: new Set(['retry']) })
    expect(groups.attention).toHaveLength(0)
    expect(groups.running).toHaveLength(1)
  })
  it('excludes archived and hidden projects and suppresses active unread', () => {
    const groups = build([thread('archive', { archived: true }), thread('hidden', { workspace: '/hidden' }), thread('active')], {
      hiddenWorkspacePaths: ['/hidden'], activeThreadId: 'active', unreadThreadIds: { archive: true, hidden: true, active: true }
    })
    expect(Object.values(groups).flat()).toHaveLength(0)
  })
  it('uses pending input in the active transcript ahead of running state', () => {
    const groups = build([thread('active')], { activeThreadId: 'active', activeWaiting: true, runningIds: new Set(['active']) })
    expect(groups.attention[0].status).toBe('waiting')
    expect(groups.running).toHaveLength(0)
  })
  it('does not reorder rows on background timestamp updates', () => {
    const rows = [thread('a'), thread('b')]
    const before = build(rows, { runningIds: new Set(['a', 'b']) }).running.map((r) => r.thread.id)
    rows[1].updatedAt = '2026-10-11T00:00:00Z'
    expect(build(rows.reverse(), { runningIds: new Set(['a', 'b']) }).running.map((r) => r.thread.id)).toEqual(before)
  })
})
