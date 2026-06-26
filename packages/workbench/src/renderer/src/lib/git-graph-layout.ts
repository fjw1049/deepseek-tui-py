import type { GitLogCommit } from '@shared/git-log'

export const GIT_GRAPH_LANE_WIDTH = 14
export const GIT_GRAPH_PADDING = 4
export const GIT_GRAPH_ROW_HEIGHT = 36
export const GIT_GRAPH_MAX_LANES = 4

export const GIT_GRAPH_COLORS = [
  '#8b5cf6',
  '#3b82f6',
  '#06b6d4',
  '#10b981',
  '#f59e0b',
  '#ec4899',
  '#6366f1',
  '#14b8a6'
] as const

export type GitGraphEdgeKind = 'straight' | 'merge-fork' | 'merge-join'

export type GitGraphEdge = {
  id: string
  kind: GitGraphEdgeKind
  colorIndex: number
  fromLane: number
  toLane: number
  startRow: number
  endRow: number
}

export type GitGraphRow = {
  hash: string
  row: number
  lane: number
  colorIndex: number
}

export type GitGraphLayout = {
  rows: GitGraphRow[]
  edges: GitGraphEdge[]
  maxLanes: number
  graphWidth: number
}

type LaneReservation = string | null

function rowIndexForHash(commits: GitLogCommit[], hash: string): number | null {
  const index = commits.findIndex((commit) => commit.hash === hash)
  return index >= 0 ? index : null
}

function ensureColumn(columns: LaneReservation[], colors: number[], index: number): void {
  while (columns.length <= index) {
    columns.push(null)
    colors.push(columns.length - 1)
  }
}

function trimColumns(columns: LaneReservation[]): void {
  while (columns.length > 0 && columns[columns.length - 1] === null) {
    columns.pop()
  }
}

function hashStillNeeded(commits: GitLogCommit[], fromRow: number, hash: string): boolean {
  for (let row = fromRow + 1; row < commits.length; row += 1) {
    const commit = commits[row]!
    if (commit.hash === hash) return true
    if (commit.parents.includes(hash)) return true
  }
  return false
}

function allocateColumn(
  columns: LaneReservation[],
  commits: GitLogCommit[],
  currentRow: number,
  forHash?: string
): number {
  if (forHash) {
    const existing = columns.findIndex((hash) => hash === forHash)
    if (existing >= 0) return existing
  }

  const free = columns.findIndex((hash) => hash === null)
  if (free >= 0) return free
  if (columns.length < GIT_GRAPH_MAX_LANES) return columns.length

  for (let index = columns.length - 1; index >= 1; index -= 1) {
    const reserved = columns[index]
    if (reserved === null) return index
    if (!hashStillNeeded(commits, currentRow, reserved)) return index
  }

  return Math.min(GIT_GRAPH_MAX_LANES - 1, columns.length - 1)
}

function assignLanes(commits: GitLogCommit[]): { lanes: number[]; laneColors: number[] } {
  const lanes = new Array<number>(commits.length).fill(0)
  const laneColors: number[] = []
  const columns: LaneReservation[] = []

  for (let row = 0; row < commits.length; row += 1) {
    const commit = commits[row]!
    const column = allocateColumn(columns, commits, row, commit.hash)
    ensureColumn(columns, laneColors, column)
    columns[column] = null
    lanes[row] = column

    const parents = commit.parents
    if (parents.length === 0) {
      trimColumns(columns)
      continue
    }

    ensureColumn(columns, laneColors, column)
    columns[column] = parents[0]!

    for (let parentIndex = 1; parentIndex < parents.length; parentIndex += 1) {
      const parent = parents[parentIndex]!
      const parentColumn = allocateColumn(columns, commits, row, parent)
      ensureColumn(columns, laneColors, parentColumn)
      columns[parentColumn] = parent
    }

    trimColumns(columns)
  }

  return { lanes, laneColors }
}

function compactLaneMap(lanes: number[]): { lanes: number[]; colors: number[] } {
  const order = [...new Set(lanes)].sort((left, right) => left - right)
  const remap = new Map(order.map((lane, index) => [lane, index]))
  return {
    lanes: lanes.map((lane) => remap.get(lane) ?? 0),
    colors: order.map((_, index) => index)
  }
}

function laneColorIndex(laneColors: number[], lane: number): number {
  return laneColors[lane] ?? lane % GIT_GRAPH_COLORS.length
}

function buildEdges(commits: GitLogCommit[], lanes: number[], laneColors: number[]): GitGraphEdge[] {
  const edges: GitGraphEdge[] = []
  const edgeKeys = new Set<string>()

  const pushEdge = (edge: GitGraphEdge): void => {
    const key = `${edge.kind}:${edge.fromLane}:${edge.toLane}:${edge.startRow}:${edge.endRow}:${edge.colorIndex}`
    if (edgeKeys.has(key)) return
    edgeKeys.add(key)
    edges.push(edge)
  }

  for (let row = 0; row < commits.length - 1; row += 1) {
    const lane = lanes[row]!
    const nextLane = lanes[row + 1]!
    if (lane !== nextLane) continue
    pushEdge({
      id: `s-${row}-${row + 1}`,
      kind: 'straight',
      colorIndex: laneColorIndex(laneColors, lane),
      fromLane: lane,
      toLane: lane,
      startRow: row,
      endRow: row + 1
    })
  }

  for (let row = 0; row < commits.length; row += 1) {
    const firstParent = commits[row]?.parents[0]
    if (!firstParent) continue
    const parentRow = rowIndexForHash(commits, firstParent)
    if (parentRow === null || parentRow <= row + 1) continue

    const lane = lanes[row]!
    const parentLane = lanes[parentRow]!
    if (lane !== parentLane || lane !== 0) continue

    let crossesOtherLane = false
    for (let crossRow = row + 1; crossRow < parentRow; crossRow += 1) {
      if (lanes[crossRow] !== lane) {
        crossesOtherLane = true
        break
      }
    }
    if (!crossesOtherLane) continue

    pushEdge({
      id: `pt-${row}-${parentRow}`,
      kind: 'straight',
      colorIndex: laneColorIndex(laneColors, lane),
      fromLane: lane,
      toLane: lane,
      startRow: row,
      endRow: parentRow
    })
  }

  for (let row = 0; row < commits.length; row += 1) {
    const commit = commits[row]!
    const commitLane = lanes[row]!
    const parents = commit.parents
    if (parents.length <= 1) continue

    for (let parentIndex = 1; parentIndex < parents.length; parentIndex += 1) {
      const parent = parents[parentIndex]!
      const parentRow = rowIndexForHash(commits, parent)
      if (parentRow === null || parentRow <= row) continue

      const branchLane = lanes[parentRow]!
      const colorIndex = laneColorIndex(laneColors, branchLane)

      pushEdge({
        id: `mf-${commit.hash.slice(0, 8)}-${parentIndex}`,
        kind: 'merge-fork',
        colorIndex,
        fromLane: commitLane,
        toLane: branchLane,
        startRow: row,
        endRow: row
      })

      if (row + 1 < commits.length && lanes[row + 1] === branchLane) {
        pushEdge({
          id: `mb-${row}-${branchLane}`,
          kind: 'straight',
          colorIndex,
          fromLane: branchLane,
          toLane: branchLane,
          startRow: row,
          endRow: row + 1
        })
      }
    }
  }

  for (let row = 0; row < commits.length - 1; row += 1) {
    const fromLane = lanes[row]!
    const toLane = lanes[row + 1]!
    if (fromLane === toLane || toLane >= fromLane) continue

    const mergeForkAtRow = edges.some(
      (edge) => edge.kind === 'merge-fork' && edge.startRow === row && edge.fromLane === fromLane
    )
    if (mergeForkAtRow) continue

    pushEdge({
      id: `mj-${row}-${fromLane}-${toLane}`,
      kind: 'merge-join',
      colorIndex: laneColorIndex(laneColors, toLane),
      fromLane,
      toLane,
      startRow: row,
      endRow: row + 1
    })
  }

  return edges
}

export function computeGitGraphLayout(commits: GitLogCommit[]): GitGraphLayout {
  if (commits.length === 0) {
    return {
      rows: [],
      edges: [],
      maxLanes: 1,
      graphWidth: GIT_GRAPH_LANE_WIDTH + GIT_GRAPH_PADDING * 2
    }
  }

  const assigned = assignLanes(commits)
  const compacted = compactLaneMap(assigned.lanes)
  const lanes = compacted.lanes
  const laneColors = compacted.colors

  const remapLane = (lane: number): number => {
    const order = [...new Set(assigned.lanes)].sort((left, right) => left - right)
    const map = new Map(order.map((value, index) => [value, index]))
    return map.get(lane) ?? 0
  }

  const rawEdges = buildEdges(commits, assigned.lanes, assigned.laneColors)
  const edges = rawEdges.map((edge) => ({
    ...edge,
    fromLane: remapLane(edge.fromLane),
    toLane: remapLane(edge.toLane)
  }))

  const rows: GitGraphRow[] = commits.map((commit, row) => ({
    hash: commit.hash,
    row,
    lane: lanes[row] ?? 0,
    colorIndex: laneColorIndex(laneColors, lanes[row] ?? 0)
  }))

  const maxLanes = Math.min(
    GIT_GRAPH_MAX_LANES,
    Math.max(1, ...rows.map((entry) => entry.lane), ...edges.flatMap((edge) => [edge.fromLane, edge.toLane])) +
      1
  )

  return {
    rows,
    edges,
    maxLanes,
    graphWidth: maxLanes * GIT_GRAPH_LANE_WIDTH + GIT_GRAPH_PADDING * 2
  }
}

export function laneCenterX(lane: number, maxLanes: number, width: number): number {
  const inner = width - GIT_GRAPH_PADDING * 2
  const step = inner / Math.max(maxLanes, 1)
  return GIT_GRAPH_PADDING + lane * step + step / 2
}
