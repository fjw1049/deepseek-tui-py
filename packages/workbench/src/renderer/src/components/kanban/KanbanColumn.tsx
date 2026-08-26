import { useState, type ReactElement, type MouseEvent, type HTMLAttributes } from 'react'
import { useTranslation } from 'react-i18next'
import { useDroppable } from '@dnd-kit/core'
import { SortableContext, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { Plus } from 'lucide-react'
import { KanbanCardView } from './KanbanCardView'
import { KanbanStatusIcon } from './KanbanStatusIcon'
import {
  DONE_RENDER_CAP,
  kanbanColumnDropId,
  type KanbanCard,
  type KanbanColumnKey
} from './kanban.logic'

const COLUMN_TITLE_KEY: Record<
  KanbanColumnKey,
  'kanbanStatusDraft' | 'kanbanStatusInProgress' | 'kanbanStatusDone'
> = {
  draft: 'kanbanStatusDraft',
  inProgress: 'kanbanStatusInProgress',
  done: 'kanbanStatusDone'
}

function SortableKanbanCard({
  card,
  onOpen,
  onContextMenu
}: {
  card: KanbanCard
  onOpen: (card: KanbanCard) => void
  onContextMenu?: (card: KanbanCard, event: MouseEvent) => void
}): ReactElement {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: card.cardId
  })

  return (
    <li className={`list-none ${isDragging ? 'z-20' : ''}`}>
      <KanbanCardView
        card={card}
        onOpen={onOpen}
        onContextMenu={onContextMenu}
        showColumnLabel={false}
        draggable
        dragBind={{
          setNodeRef,
          style: {
            transform: isDragging ? undefined : CSS.Translate.toString(transform),
            transition: isDragging ? undefined : transition
          },
          attributes: attributes as HTMLAttributes<HTMLElement>,
          listeners: listeners as HTMLAttributes<HTMLElement> | undefined,
          isDragging
        }}
      />
    </li>
  )
}

export function KanbanColumn({
  projectId,
  columnKey,
  cards,
  onOpenCard,
  onCardContextMenu,
  sortable = false,
  droppable = false,
  activeCard = null,
  onNewCard
}: {
  projectId: string
  columnKey: KanbanColumnKey
  cards: readonly KanbanCard[]
  onOpenCard: (card: KanbanCard) => void
  onCardContextMenu?: (card: KanbanCard, event: MouseEvent) => void
  sortable?: boolean
  droppable?: boolean
  activeCard?: KanbanCard | null
  onNewCard?: () => void
}): ReactElement {
  const { t } = useTranslation('common')
  const dropId = kanbanColumnDropId(projectId, columnKey)
  const { isOver, setNodeRef } = useDroppable({ id: dropId, disabled: !droppable })
  const [showAll, setShowAll] = useState(false)

  const capped =
    columnKey === 'done' && !showAll && cards.length > DONE_RENDER_CAP
      ? cards.slice(0, DONE_RENDER_CAP)
      : cards
  const hiddenCount = cards.length - capped.length
  const dropHint =
    droppable &&
    activeCard &&
    activeCard.column !== columnKey &&
    isOver

  return (
    <section className="flex w-80 shrink-0 flex-col">
      <div className="flex shrink-0 items-center gap-1.5 py-2 pr-1">
        <KanbanStatusIcon column={columnKey} />
        <h2 className="min-w-0 flex-1 truncate text-[15px] font-semibold text-ds-ink">
          {t(COLUMN_TITLE_KEY[columnKey])}
        </h2>
        <span className="text-[13px] text-ds-faint">{cards.length}</span>
        {onNewCard ? (
          <button
            type="button"
            className="ds-no-drag inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-ds-faint transition hover:bg-ds-hover hover:text-ds-ink"
            aria-label={t('kanbanNewTask')}
            title={t('kanbanNewTask')}
            onClick={onNewCard}
          >
            <Plus className="h-4 w-4" strokeWidth={2} />
          </button>
        ) : null}
      </div>
      <ul
        ref={setNodeRef}
        className={`flex min-h-[12rem] flex-1 flex-col gap-2.5 overflow-y-auto rounded-xl py-1 pr-1 transition ${
          isOver ? 'bg-ds-hover' : ''
        } ${dropHint ? 'ring-1 ring-sky-500/40' : ''}`}
      >
        {sortable ? (
          <SortableContext
            items={capped.map((card) => card.cardId)}
            strategy={verticalListSortingStrategy}
          >
            {capped.map((card) => (
              <SortableKanbanCard
                key={card.cardId}
                card={card}
                onOpen={onOpenCard}
                onContextMenu={onCardContextMenu}
              />
            ))}
          </SortableContext>
        ) : (
          capped.map((card) => (
            <li key={card.cardId} className="list-none">
              <KanbanCardView
                card={card}
                onOpen={onOpenCard}
                onContextMenu={onCardContextMenu}
                showColumnLabel={false}
              />
            </li>
          ))
        )}
        {sortable && capped.length === 0 ? (
          <li className="list-none px-2 py-6 text-center text-[12px] leading-5 text-ds-faint">
            {t('kanbanDraftDropHint')}
          </li>
        ) : null}
        {hiddenCount > 0 ? (
          <li className="list-none">
            <button
              type="button"
              className="w-full rounded-lg px-3 py-1.5 text-center text-xs text-ds-faint transition hover:bg-ds-hover hover:text-ds-ink"
              onClick={() => setShowAll(true)}
            >
              {t('kanbanShowMore', { count: hiddenCount })}
            </button>
          </li>
        ) : null}
      </ul>
    </section>
  )
}
