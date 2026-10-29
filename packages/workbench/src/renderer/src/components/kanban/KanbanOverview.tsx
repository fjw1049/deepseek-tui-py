import { memo, useLayoutEffect, useRef, useState, type ReactElement, type MouseEvent, type RefObject } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronRight, Plus } from 'lucide-react'
import { KanbanCardView } from './KanbanCardView'
import {
  overviewVisibleCards,
  type KanbanBoard,
  type KanbanCard,
  type KanbanProjectBoard
} from './kanban.logic'

// Memoized so mounting a column while scrolling does not re-render its neighbours.
const OverviewProjectColumn = memo(function OverviewProjectColumn({
  projectBoard,
  onOpenProject,
  onOpenCard,
  onCardContextMenu,
  onNewTask
}: {
  projectBoard: KanbanProjectBoard
  onOpenProject: (projectId: string) => void
  onOpenCard: (card: KanbanCard) => void
  onCardContextMenu?: (card: KanbanCard, event: MouseEvent) => void
  onNewTask: (project: KanbanProjectBoard) => void
}): ReactElement {
  const { t } = useTranslation('common')
  const { visibleCards, hiddenCount } = overviewVisibleCards(projectBoard)

  return (
    <section className="flex w-80 shrink-0 flex-col">
      <div className="flex shrink-0 items-center gap-1.5 py-2 pr-1">
        <button
          type="button"
          onClick={() => onOpenProject(projectBoard.projectId)}
          className="group/kanban-project flex min-w-0 flex-1 items-center gap-2 rounded-lg py-1 pr-1.5 text-left transition hover:bg-ds-hover"
        >
          <h2 className="min-w-0 truncate text-[15px] font-semibold text-ds-ink">
            {projectBoard.projectName}
          </h2>
          <span className="text-[13px] text-ds-faint">{projectBoard.totalCount}</span>
          <ChevronRight className="ml-auto h-4 w-4 shrink-0 text-ds-faint opacity-0 transition group-hover/kanban-project:opacity-100" />
        </button>
        <button
          type="button"
          className="ds-no-drag inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-ds-faint transition hover:bg-ds-hover hover:text-ds-ink"
          aria-label={t('kanbanNewTaskInProject', { project: projectBoard.projectName })}
          title={t('kanbanNewTaskInProject', { project: projectBoard.projectName })}
          onClick={() => onNewTask(projectBoard)}
        >
          <Plus className="h-4 w-4" strokeWidth={2} />
        </button>
      </div>
      <ul className="flex min-h-0 flex-1 flex-col gap-2.5 overflow-y-auto py-1 pr-1">
        {visibleCards.map((card) => (
          <li key={card.cardId} className="list-none">
            <KanbanCardView
              card={card}
              onOpen={onOpenCard}
              onContextMenu={onCardContextMenu}
            />
          </li>
        ))}
        {hiddenCount > 0 ? (
          <li className="list-none">
            <button
              type="button"
              onClick={() => onOpenProject(projectBoard.projectId)}
              className="w-full rounded-lg px-3 py-2 text-center text-[13px] text-ds-faint transition hover:bg-ds-hover hover:text-ds-ink"
            >
              {t('kanbanShowMore', { count: hiddenCount })}
            </button>
          </li>
        ) : null}
      </ul>
    </section>
  )
})

// Columns are w-80 (20rem) with gap-5 (1.25rem) inside px-8 (2rem) padding.
const COLUMN_STRIDE_REM = 21.25
const EDGE_PADDING_REM = 2
const OVERSCAN_COLUMNS = 3

/** Columns intersecting the horizontal viewport (plus overscan); all of them without layout. */
function useVisibleColumnRange(ref: RefObject<HTMLDivElement | null>, count: number): [number, number] {
  const [range, setRange] = useState<[number, number]>(() => [0, Math.min(count, 12)])
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    let frame: number | null = null
    // Measured on resize only: reading styles per scroll frame forces a style recalc.
    let rem = 16
    let width = 0
    const measure = (): void => {
      rem = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16
      width = el.clientWidth
    }
    const update = (): void => {
      frame = null
      let start = 0
      let end = count
      if (width > 0) {
        const stride = COLUMN_STRIDE_REM * rem
        const offset = el.scrollLeft - EDGE_PADDING_REM * rem
        start = Math.max(0, Math.floor(offset / stride) - OVERSCAN_COLUMNS)
        end = Math.min(count, Math.ceil((offset + width) / stride) + OVERSCAN_COLUMNS)
      }
      setRange((prev) => (prev[0] === start && prev[1] === end ? prev : [start, end]))
    }
    const schedule = (): void => {
      if (frame === null) frame = requestAnimationFrame(update)
    }
    measure()
    update()
    el.addEventListener('scroll', schedule, { passive: true })
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(() => { measure(); schedule() })
    observer?.observe(el)
    return () => {
      el.removeEventListener('scroll', schedule)
      observer?.disconnect()
      if (frame !== null) cancelAnimationFrame(frame)
    }
  }, [ref, count])
  return [Math.min(range[0], count), Math.min(range[1], count)]
}

export function KanbanOverview({
  board,
  onOpenProject,
  onOpenCard,
  onCardContextMenu,
  onNewTask
}: {
  board: KanbanBoard
  onOpenProject: (projectId: string) => void
  onOpenCard: (card: KanbanCard) => void
  onCardContextMenu?: (card: KanbanCard, event: MouseEvent) => void
  onNewTask: (project: KanbanProjectBoard) => void
}): ReactElement {
  const { t } = useTranslation('common')
  const scrollerRef = useRef<HTMLDivElement>(null)
  // Hundreds of projects made every horizontal scroll frame walk every column; mount only nearby ones.
  const [start, end] = useVisibleColumnRange(scrollerRef, board.projects.length)

  if (board.projects.length === 0) {
    return (
      <div className="flex h-full items-center justify-center px-6">
        <div className="max-w-sm text-center">
          <div className="text-sm font-medium text-ds-ink">{t('kanbanEmptyTitle')}</div>
          <div className="mt-1 text-sm text-ds-faint">{t('kanbanEmptyHint')}</div>
        </div>
      </div>
    )
  }

  return (
    <div ref={scrollerRef} className="flex h-full min-h-0 gap-5 overflow-x-auto px-8 pb-6" style={{ overflowAnchor: 'none' }}>
      {/* Spacers (not padding) stand in for unmounted columns: padding would widen the page. */}
      {start > 0 ? <ColumnSpacer columns={start} /> : null}
      {board.projects.slice(start, end).map((projectBoard) => (
        <OverviewProjectColumn
          key={projectBoard.projectId}
          projectBoard={projectBoard}
          onOpenProject={onOpenProject}
          onOpenCard={onOpenCard}
          onCardContextMenu={onCardContextMenu}
          onNewTask={onNewTask}
        />
      ))}
      {end < board.projects.length ? <ColumnSpacer columns={board.projects.length - end} /> : null}
    </div>
  )
}

/** Same width as `columns` columns; the container gap after it completes the last stride. */
function ColumnSpacer({ columns }: { columns: number }): ReactElement {
  return <div aria-hidden className="shrink-0" style={{ width: `calc(${columns} * ${COLUMN_STRIDE_REM}rem - 1.25rem)` }} />
}
