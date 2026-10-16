import { describe, expect, it } from 'vitest'
import { reuseStableTurns } from './message-timeline-logic'

const user = (id: string) => ({ id, kind: 'user' as const })
const tool = (id: string, status = 'running') => ({ id, kind: 'tool' as const, status })

describe('reuseStableTurns', () => {
  it('reuses untouched turns and replaces only the changed one', () => {
    const u1 = user('u1')
    const u2 = user('u2')
    const t1 = tool('t1', 'success')
    const t2 = tool('t2')
    const prev = [{ user: u1, blocks: [t1] }, { user: u2, blocks: [t2] }]
    const next = [{ user: u1, blocks: [t1] }, { user: u2, blocks: [{ ...t2, status: 'success' }] }]
    const result = reuseStableTurns(prev, next)
    expect(result[0]).toBe(prev[0])
    expect(result[1]).toBe(next[1])
    expect(result).not.toBe(prev)
  })

  it('returns the previous array when every turn is unchanged', () => {
    const u1 = user('u1')
    const t1 = tool('t1')
    const prev = [{ user: u1, blocks: [t1] }]
    expect(reuseStableTurns(prev, [{ user: u1, blocks: [t1] }])).toBe(prev)
  })

  it('treats appended blocks and new turns as changes', () => {
    const u1 = user('u1')
    const t1 = tool('t1')
    const prev = [{ user: u1, blocks: [t1] }]
    const grown = reuseStableTurns(prev, [{ user: u1, blocks: [t1, tool('t2')] }])
    expect(grown).not.toBe(prev)
    expect(grown[0]).not.toBe(prev[0])
    expect(reuseStableTurns(prev, [...prev, { user: user('u2'), blocks: [] }])).toHaveLength(2)
  })

  it('keys user-less turns by their first block', () => {
    const s = { id: 's1', kind: 'system' as const }
    const prev = [{ blocks: [s] }]
    expect(reuseStableTurns(prev, [{ blocks: [s] }])).toBe(prev)
  })
})
