import type { ReactElement } from 'react'
import type { GitGraphEdge, GitGraphLayout } from '../../lib/git-graph-layout'
import { GIT_GRAPH_COLORS, GIT_GRAPH_ROW_HEIGHT, laneCenterX } from '../../lib/git-graph-layout'

type Props = {
  row: number
  lane: number
  colorIndex: number
  layout: GitGraphLayout
  isHead: boolean
  isUpstream: boolean
}

function edgeVisibleInRow(edge: GitGraphEdge, row: number): boolean {
  return edge.startRow <= row && edge.endRow >= row
}

function sliceStraightPath(
  edge: GitGraphEdge,
  row: number,
  x: number,
  height: number
): string | null {
  if (edge.kind !== 'straight' || !edgeVisibleInRow(edge, row)) return null

  const midY = height / 2
  let y1 = 0
  let y2 = height

  if (edge.startRow === row) y1 = midY
  if (edge.endRow === row) y2 = midY

  if (y2 <= y1 + 0.5) return null
  return `M ${x} ${y1} L ${x} ${y2}`
}

function forkPath(
  edge: GitGraphEdge,
  row: number,
  fromX: number,
  toX: number,
  height: number
): string | null {
  if (edge.kind !== 'merge-fork' || edge.startRow !== row) return null
  const midY = height / 2
  const bend = height * 0.78
  return `M ${fromX} ${midY} C ${fromX} ${bend}, ${toX} ${bend}, ${toX} ${height}`
}

function joinPath(
  edge: GitGraphEdge,
  row: number,
  fromX: number,
  toX: number,
  height: number
): string | null {
  if (edge.kind !== 'merge-join' || edge.startRow !== row) return null
  const midY = height / 2
  const bend = height * 0.78
  return `M ${fromX} ${midY} C ${fromX} ${bend}, ${toX} ${bend}, ${toX} ${height}`
}

function bridgePath(
  edge: GitGraphEdge,
  row: number,
  x: number,
  height: number
): string | null {
  if (edge.kind !== 'straight' || edge.startRow + 1 !== row) return null
  if (edge.endRow !== row) return null
  return `M ${x} 0 L ${x} ${height / 2}`
}

export function GitGraphRowSvg({
  row,
  lane,
  colorIndex,
  layout,
  isHead,
  isUpstream
}: Props): ReactElement {
  const height = GIT_GRAPH_ROW_HEIGHT
  const { edges, maxLanes, graphWidth } = layout
  const dotX = laneCenterX(lane, maxLanes, graphWidth)
  const dotColor = GIT_GRAPH_COLORS[colorIndex % GIT_GRAPH_COLORS.length] ?? GIT_GRAPH_COLORS[0]
  const dotFill = isHead ? dotColor : isUpstream ? '#f59e0b' : dotColor

  const pathStrokes: Array<{ d: string; stroke: string }> = []
  for (const edge of edges) {
    if (!edgeVisibleInRow(edge, row)) continue
    const stroke = GIT_GRAPH_COLORS[edge.colorIndex % GIT_GRAPH_COLORS.length] ?? GIT_GRAPH_COLORS[0]
    const fromX = laneCenterX(edge.fromLane, maxLanes, graphWidth)
    const toX = laneCenterX(edge.toLane, maxLanes, graphWidth)

    const straight = sliceStraightPath(edge, row, fromX, height)
    if (straight) pathStrokes.push({ d: straight, stroke })

    const bridge = bridgePath(edge, row, toX, height)
    if (bridge) pathStrokes.push({ d: bridge, stroke })

    const fork = forkPath(edge, row, fromX, toX, height)
    if (fork) pathStrokes.push({ d: fork, stroke })

    const join = joinPath(edge, row, fromX, toX, height)
    if (join) pathStrokes.push({ d: join, stroke })
  }

  return (
    <svg
      width={graphWidth}
      height={height}
      className="block shrink-0 overflow-visible"
      aria-hidden
      viewBox={`0 0 ${graphWidth} ${height}`}
    >
      {pathStrokes.map((entry, index) => (
        <path
          key={`${row}-${index}`}
          d={entry.d}
          fill="none"
          stroke={entry.stroke}
          strokeWidth={2}
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeOpacity={0.65}
        />
      ))}
      <circle
        cx={dotX}
        cy={height / 2}
        r={isHead || isUpstream ? 4.5 : 3.5}
        fill={dotFill}
        stroke="var(--ds-card, #fff)"
        strokeWidth={2}
      />
    </svg>
  )
}

export { GIT_GRAPH_ROW_HEIGHT }
