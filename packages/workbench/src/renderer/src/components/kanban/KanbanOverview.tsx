import type { ReactElement, MouseEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronRight, Plus } from 'lucide-react'
import { KanbanCardView } from './KanbanCardView'
import {
  overviewVisibleCards,
  type KanbanBoard,
  type KanbanCard,
  type KanbanProjectBoard
} from './kanban.logic'

function OverviewProjectColumn({
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
    <div className="flex h-full min-h-0 gap-5 overflow-x-auto px-8 pb-6">
      {board.projects.map((projectBoard) => (
        <OverviewProjectColumn
          key={projectBoard.projectId}
          projectBoard={projectBoard}
          onOpenProject={onOpenProject}
          onOpenCard={onOpenCard}
          onCardContextMenu={onCardContextMenu}
          onNewTask={onNewTask}
        />
      ))}
    </div>
  )
}
