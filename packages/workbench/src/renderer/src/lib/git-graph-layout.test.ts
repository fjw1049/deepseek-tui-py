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
    expect(layout.maxLanes).toBe(1)
    expect(
      layout.edges.every((edge) => edge.fromLane === 0 && edge.toLane === 0)
    ).toBe(true)
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
  })

  it('keeps the mainline pinned to lane 0', () => {
    const commits = [
      commit('main1', ['merge']),
      commit('merge', ['main2', 'branch1']),
      commit('branch1', ['branch2']),
      commit('branch2', ['fork']),
      commit('main2', ['fork']),
      commit('fork', [])
    ]
    const layout = computeGitGraphLayout(commits)
    const mainlineRows = layout.rows.filter((row) => row.isMainline)
    expect(mainlineRows.map((row) => row.hash)).toEqual([
      'main1',
      'merge',
      'main2',
      'fork'
    ])
    expect(mainlineRows.every((row) => row.lane === 0)).toBe(true)

    const branchRows = layout.rows.filter((row) => !row.isMainline)
    expect(branchRows.map((row) => row.hash)).toEqual(['branch1', 'branch2'])
    expect(branchRows.every((row) => row.lane === 1)).toBe(true)
  })

  it('draws a continuous mainline edge across merged side branch rows', () => {
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
        edge.fromRow === 1 && edge.toRow === 4 && edge.fromLane === 0 && edge.toLane === 0
    )
    expect(passThrough).toBeDefined()
  })

  it('connects side branches back into the merge target', () => {
    const commits = [
      commit('merge', ['main2', 'branch1']),
      commit('branch1', ['fork']),
      commit('main2', ['fork']),
      commit('fork', [])
    ]
    const layout = computeGitGraphLayout(commits)
    const forkEdge = layout.edges.find((edge) => edge.fromRow === 0 && edge.viaLane === 1)
    expect(forkEdge).toBeDefined()
    const joinEdge = layout.edges.find(
      (edge) => edge.fromRow === 1 && edge.toRow === 3 && edge.toLane === 0
    )
    expect(joinEdge).toBeDefined()
  })

  it('runs unresolved parent lines off the bottom of the graph', () => {
    const commits = [
      commit('c1', ['c2']),
      commit('c2', ['outside'])
    ]
    const layout = computeGitGraphLayout(commits)
    const tail = layout.edges.find((edge) => edge.toRow === commits.length)
    expect(tail).toBeDefined()
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
