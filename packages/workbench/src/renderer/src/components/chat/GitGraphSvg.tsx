import type { ReactElement } from 'react'
import type { GitGraphEdge, GitGraphLayout } from '../../lib/git-graph-layout'
import {
  GIT_GRAPH_COLORS,
  GIT_GRAPH_ROW_HEIGHT,
  laneCenterX,
  rowCenterY
} from '../../lib/git-graph-layout'

type Props = {
  layout: GitGraphLayout
  headHash: string
}

function edgePath(edge: GitGraphEdge, maxLanes: number, width: number): string {
  const rowH = GIT_GRAPH_ROW_HEIGHT
  const x1 = laneCenterX(edge.fromLane, maxLanes, width)
  const xv = laneCenterX(edge.viaLane, maxLanes, width)
  const x2 = laneCenterX(edge.toLane, maxLanes, width)
  const y1 = rowCenterY(edge.fromRow)
  const y2 = rowCenterY(edge.toRow)

  if (x1 === xv && xv === x2) {
    return `M ${x1} ${y1} L ${x2} ${y2}`
  }

  // Both bends squeezed into a single row: draw one smooth S-curve.
  if (edge.toRow - edge.fromRow <= 1) {
    const midY = (y1 + y2) / 2
    return `M ${x1} ${y1} C ${x1} ${midY}, ${x2} ${midY}, ${x2} ${y2}`
  }

  const parts = [`M ${x1} ${y1}`]
  let y = y1

  if (x1 !== xv) {
    const bendEnd = y1 + rowH
    parts.push(`C ${x1} ${y1 + rowH / 2}, ${xv} ${y1 + rowH / 2}, ${xv} ${bendEnd}`)
    y = bendEnd
  }

  if (xv !== x2) {
    const bendStart = y2 - rowH
    if (bendStart > y) parts.push(`L ${xv} ${bendStart}`)
    parts.push(`C ${xv} ${y2 - rowH / 2}, ${x2} ${y2 - rowH / 2}, ${x2} ${y2}`)
  } else {
    parts.push(`L ${x2} ${y2}`)
  }

  return parts.join(' ')
}

export function GitGraphSvg({ layout, headHash }: Props): ReactElement {
  const { rows, edges, maxLanes, graphWidth, rowCount } = layout
  const height = rowCount * GIT_GRAPH_ROW_HEIGHT

  return (
    <svg
      width={graphWidth}
      height={height}
      viewBox={`0 0 ${graphWidth} ${height}`}
      className="block"
      aria-hidden
    >
      {edges.map((edge) => (
        <path
          key={edge.id}
          d={edgePath(edge, maxLanes, graphWidth)}
          fill="none"
          stroke={GIT_GRAPH_COLORS[edge.colorIndex % GIT_GRAPH_COLORS.length]}
          strokeWidth={2}
          strokeLinecap="round"
          strokeOpacity={0.85}
        />
      ))}
      {rows.map((row) => {
        const cx = laneCenterX(row.lane, maxLanes, graphWidth)
        const cy = rowCenterY(row.row)
        const color = GIT_GRAPH_COLORS[row.colorIndex % GIT_GRAPH_COLORS.length]
        const isHead = row.hash === headHash
        return (
          <g key={row.hash}>
            <circle cx={cx} cy={cy} r={isHead ? 7.5 : 6.5} fill={color} fillOpacity={0.22} />
            {isHead ? (
              <circle
                cx={cx}
                cy={cy}
                r={3.6}
                fill="var(--ds-card, #fff)"
                stroke={color}
                strokeWidth={2.2}
              />
            ) : (
              <circle cx={cx} cy={cy} r={3.4} fill={color} />
            )}
          </g>
        )
      })}
    </svg>
  )
}
