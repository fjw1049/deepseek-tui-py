import { describe, expect, it } from 'vitest'
import type { GitLogCommit } from '@shared/git-log'
import { computeGitGraphLayout, GIT_GRAPH_MAX_LANES } from './git-graph-layout'

function commit(
  hash: string,
  parents: string[],
  subject = hash
): GitLogCommit {
  return {
    hash,
    shortHash: hash.slice(0, 7),
    parents,
    subject,
    author: 'test',
    authoredAt: new Date().toISOString()
  }
}

describe('computeGitGraphLayout', () => {
  it('assigns a single lane for linear history', () => {
    const commits = [
      commit('c1', ['c2']),
      commit('c2', ['c3']),
      commit('c3', [])
    ]
    const layout = computeGitGraphLayout(commits)
    expect(layout.rows.every((row) => row.lane === 0)).toBe(true)
    expect(layout.edges.some((edge) => edge.kind === 'straight')).toBe(true)
  })

  it('opens a second lane for merge commits', () => {
    const commits = [
      commit('main1', ['merge']),
      commit('merge', ['main2', 'branch1']),
      commit('branch1', ['branch2']),
      commit('branch2', ['fork']),
      commit('main2', ['fork']),
      commit('fork', [])
    ]
    const layout = computeGitGraphLayout(commits)
    const lanes = new Set(layout.rows.map((row) => row.lane))
    expect(lanes.size).toBeGreaterThanOrEqual(2)
    expect(layout.edges.some((edge) => edge.kind === 'merge-fork')).toBe(true)
  })

  it('keeps main lane continuous across merged side branch rows', () => {
    const commits = [
      commit('main1', ['merge']),
      commit('merge', ['main2', 'branch1']),
      commit('branch1', ['branch2']),
      commit('branch2', ['fork']),
      commit('main2', ['fork']),
      commit('fork', [])
    ]
    const layout = computeGitGraphLayout(commits)
    const passThrough = layout.edges.find(
      (edge) =>
        edge.kind === 'straight' &&
        edge.fromLane === 0 &&
        edge.startRow === 1 &&
        edge.endRow === 4
    )
    expect(passThrough).toBeDefined()
  })

  it('caps lane count for dense histories', () => {
    const commits = [
      commit('m0', ['m1']),
      commit('m1', ['m2', 'b1']),
      commit('b1', ['b2']),
      commit('b2', ['m3']),
      commit('m2', ['m3', 'b3']),
      commit('b3', ['m4']),
      commit('m3', ['m4', 'b4']),
      commit('b4', ['root']),
      commit('m4', ['root']),
      commit('root', [])
    ]
    const layout = computeGitGraphLayout(commits)
    expect(layout.maxLanes).toBeLessThanOrEqual(GIT_GRAPH_MAX_LANES)
    expect(Math.max(...layout.rows.map((row) => row.lane))).toBeLessThan(GIT_GRAPH_MAX_LANES)
  })
})
