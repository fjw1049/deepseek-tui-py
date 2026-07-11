import type { GitLogCommit } from '@shared/git-log'

export const GIT_GRAPH_LANE_WIDTH = 16
export const GIT_GRAPH_PADDING = 4
export const GIT_GRAPH_ROW_HEIGHT = 36
export const GIT_GRAPH_MAX_LANES = 4

export const GIT_GRAPH_COLORS = [
  '#3b82f6',
  '#f59e0b',
  '#ef4444',
  '#10b981',
  '#8b5cf6',
  '#ec4899',
  '#06b6d4',
  '#6366f1'
] as const

/**
 * An edge is a continuous line between two commit dots (or the bottom of the
 * graph for lines whose parent falls outside the loaded window).
 *
 * The line starts at (fromRow, fromLane), immediately bends into `viaLane`
 * if needed, travels straight down `viaLane`, then bends into (toRow, toLane).
 */
export type GitGraphEdge = {
  id: string
  fromRow: number
  fromLane: number
  /** May equal the number of rows: the line runs off the bottom edge. */
  toRow: number
  toLane: number
  viaLane: number
  colorIndex: number
}

export type GitGraphRow = {
  hash: string
  row: number
  lane: number
  colorIndex: number
  /** True when the commit sits on the first-parent chain of the top commit. */
  isMainline: boolean
}

export type GitGraphLayout = {
  rows: GitGraphRow[]
  edges: GitGraphEdge[]
  maxLanes: number
  graphWidth: number
  rowCount: number
}

type Column = {
  lane: number
  expectedHash: string
  colorIndex: number
  anchorRow: number
  anchorLane: number
}

function mainlineHashes(commits: GitLogCommit[]): Set<string> {
  const byHash = new Map(commits.map((commit) => [commit.hash, commit]))
  const chain = new Set<string>()
  let current: GitLogCommit | undefined = commits[0]
  while (current && !chain.has(current.hash)) {
    chain.add(current.hash)
    const firstParent: string | undefined = current.parents[0]
    current = firstParent ? byHash.get(firstParent) : undefined
  }
  return chain
}

export function computeGitGraphLayout(commits: GitLogCommit[]): GitGraphLayout {
  if (commits.length === 0) {
    return {
      rows: [],
      edges: [],
      maxLanes: 1,
      graphWidth: GIT_GRAPH_LANE_WIDTH + GIT_GRAPH_PADDING * 2,
      rowCount: 0
    }
  }

  const mainline = mainlineHashes(commits)
  const columns: Array<Column | null> = []
  const rows: GitGraphRow[] = []
  const edges: GitGraphEdge[] = []
  let nextColor = 0

  const allocLane = (): number => {
    const free = columns.findIndex((column) => column === null)
    if (free >= 0) return free
    if (columns.length < GIT_GRAPH_MAX_LANES) {
      columns.push(null)
      return columns.length - 1
    }
    return -1
  }

  for (let row = 0; row < commits.length; row += 1) {
    const commit = commits[row]!
    const matching = columns.filter(
      (column): column is Column => column !== null && column.expectedHash === commit.hash
    )

    let lane: number
    let colorIndex: number

    if (matching.length > 0) {
      lane = matching[0]!.lane
      colorIndex = matching[0]!.colorIndex
      for (const column of matching) {
        edges.push({
          id: `e-${column.anchorRow}-${column.lane}-${row}`,
          fromRow: column.anchorRow,
          fromLane: column.anchorLane,
          toRow: row,
          toLane: lane,
          viaLane: column.lane,
          colorIndex: column.colorIndex
        })
        columns[column.lane] = null
      }
    } else {
      const alloc = allocLane()
      lane = alloc >= 0 ? alloc : GIT_GRAPH_MAX_LANES - 1
      colorIndex = nextColor % GIT_GRAPH_COLORS.length
      nextColor += 1
    }

    rows.push({
      hash: commit.hash,
      row,
      lane,
      colorIndex,
      isMainline: mainline.has(commit.hash)
    })

    const firstParent = commit.parents[0]
    if (firstParent) {
      columns[lane] = {
        lane,
        expectedHash: firstParent,
        colorIndex,
        anchorRow: row,
        anchorLane: lane
      }
    }

    for (let parentIndex = 1; parentIndex < commit.parents.length; parentIndex += 1) {
      const parent = commit.parents[parentIndex]!
      if (parent === firstParent) continue
      const parentLane = allocLane()
      if (parentLane < 0) continue
      columns[parentLane] = {
        lane: parentLane,
        expectedHash: parent,
        colorIndex: nextColor % GIT_GRAPH_COLORS.length,
        anchorRow: row,
        anchorLane: lane
      }
      nextColor += 1
    }
  }

  for (const column of columns) {
    if (!column) continue
    edges.push({
      id: `e-${column.anchorRow}-${column.lane}-end`,
      fromRow: column.anchorRow,
      fromLane: column.anchorLane,
      toRow: commits.length,
      toLane: column.lane,
      viaLane: column.lane,
      colorIndex: column.colorIndex
    })
  }

  const maxLanes = Math.max(
    1,
    ...rows.map((entry) => entry.lane + 1),
    ...edges.map((edge) => Math.max(edge.fromLane, edge.toLane, edge.viaLane) + 1)
  )

  return {
    rows,
    edges,
    maxLanes,
    graphWidth: maxLanes * GIT_GRAPH_LANE_WIDTH + GIT_GRAPH_PADDING * 2,
    rowCount: commits.length
  }
}

export function laneCenterX(lane: number, maxLanes: number, width: number): number {
  const inner = width - GIT_GRAPH_PADDING * 2
  const step = inner / Math.max(maxLanes, 1)
  return GIT_GRAPH_PADDING + lane * step + step / 2
}

export function rowCenterY(row: number): number {
  return row * GIT_GRAPH_ROW_HEIGHT + GIT_GRAPH_ROW_HEIGHT / 2
}
