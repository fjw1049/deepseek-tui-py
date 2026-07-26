import { describe, expect, it } from 'vitest'
import type { NormalizedThread } from '../agent/types'
import {
  compareProjectGroups,
  isProjectSortMode,
  sortProjectGroups,
  type ProjectGroup
} from './sidebar-project-sort'

function thread(
  partial: Pick<NormalizedThread, 'id' | 'updatedAt'> &
    Partial<NormalizedThread>
): NormalizedThread {
  return {
    title: partial.title ?? partial.id,
    model: 'm',
    mode: 'agent',
    ...partial
  }
}

function group(path: string, threads: NormalizedThread[]): ProjectGroup {
  return [path, threads]
}

describe('isProjectSortMode', () => {
  it('accepts known modes', () => {
    expect(isProjectSortMode('recent')).toBe(true)
    expect(isProjectSortMode('name_asc')).toBe(true)
    expect(isProjectSortMode('created')).toBe(true)
    expect(isProjectSortMode('nope')).toBe(false)
  })
})

describe('compareProjectGroups / sortProjectGroups', () => {
  const alpha = group('/ws/alpha', [
    thread({ id: 'a1', updatedAt: '2026-01-01T00:00:00Z', createdAt: '2026-01-01T00:00:00Z' })
  ])
  const beta = group('/ws/beta', [
    thread({ id: 'b1', updatedAt: '2026-06-01T00:00:00Z', createdAt: '2025-01-01T00:00:00Z' }),
    thread({ id: 'b2', updatedAt: '2026-03-01T00:00:00Z', createdAt: '2025-06-01T00:00:00Z' })
  ])
  const empty = group('/ws/empty', [])
  const gamma = group('/ws/gamma', [
    thread({ id: 'g1', updatedAt: '2026-02-01T00:00:00Z', createdAt: '2026-05-01T00:00:00Z' })
  ])

  it('sorts by recent activity (new → old)', () => {
    const sorted = sortProjectGroups([alpha, beta, gamma], 'recent')
    expect(sorted.map(([p]) => p)).toEqual(['/ws/beta', '/ws/gamma', '/ws/alpha'])
  })

  it('sorts by project name', () => {
    expect(sortProjectGroups([gamma, alpha, beta], 'name_asc').map(([p]) => p)).toEqual([
      '/ws/alpha',
      '/ws/beta',
      '/ws/gamma'
    ])
  })

  it('sorts by thread count many → few, empty last among counts', () => {
    const sorted = sortProjectGroups([alpha, beta, empty], 'thread_count')
    expect(sorted.map(([p]) => p)).toEqual(['/ws/beta', '/ws/alpha', '/ws/empty'])
  })

  it('sorts by earliest creation new → old; empty / missing last', () => {
    // gamma earliest created 2026-05, alpha 2026-01, beta 2025-01 → gamma, alpha, beta
    const sorted = sortProjectGroups([beta, alpha, gamma, empty], 'created')
    expect(sorted.map(([p]) => p)).toEqual(['/ws/gamma', '/ws/alpha', '/ws/beta', '/ws/empty'])
  })

  it('uses name as stable tiebreak for equal activity', () => {
    const a = group('/ws/aaa', [
      thread({ id: '1', updatedAt: '2026-01-01T00:00:00Z' })
    ])
    const z = group('/ws/zzz', [
      thread({ id: '2', updatedAt: '2026-01-01T00:00:00Z' })
    ])
    expect(compareProjectGroups(a, z, 'recent')).toBeLessThan(0)
    expect(compareProjectGroups(z, a, 'recent')).toBeGreaterThan(0)
  })
})
