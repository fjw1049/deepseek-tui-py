import { useRef, useState, type ReactElement, type MouseEvent } from 'react'
import { useTranslation } from 'react-i18next'
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  closestCorners,
  pointerWithin,
  useSensor,
  useSensors,
  type CollisionDetection,
  type DragEndEvent,
  type DragStartEvent
} from '@dnd-kit/core'
import { KanbanCardView } from './KanbanCardView'
import { KanbanColumn } from './KanbanColumn'
import {
  parseKanbanColumnDropId,
  reorderDraftCardIds,
  type KanbanCard,
  type KanbanColumnKey,
  type KanbanProjectBoard
} from './kanban.logic'

function resolveDropColumn(board: KanbanProjectBoard, overId: string): KanbanColumnKey | null {
  const columnDrop = parseKanbanColumnDropId(overId)
  if (columnDrop) {
    return columnDrop.projectId === board.projectId ? columnDrop.column : null
  }
  return board.draft.some((card) => card.cardId === overId) ? 'draft' : null
}

const collisionDetection: CollisionDetection = (args) => {
  const pointerCollisions = pointerWithin(args)
  if (pointerCollisions.length > 0) return pointerCollisions
  return closestCorners(args)
}

export function KanbanProjectBoardView({
  board,
  onOpenCard,
  onCardContextMenu,
  onNewTask,
  onReorderDrafts,
  onDispatchDraft
}: {
  board: KanbanProjectBoard
  onOpenCard: (card: KanbanCard) => void
  onCardContextMenu?: (card: KanbanCard, event: MouseEvent) => void
  onNewTask: () => void
  onReorderDrafts: (cardIds: string[]) => void
  onDispatchDraft: (card: KanbanCard) => void | Promise<void>
}): ReactElement {
  const { t } = useTranslation('common')
  const [activeCard, setActiveCard] = useState<KanbanCard | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const suppressClickRef = useRef(false)

  const sensors = useSensors(
    useSensor(PointerSensor, {
      // Keep clicks working; start drag after a short move.
      activationConstraint: { distance: 8 }
    })
  )

  const handleOpenCard = (card: KanbanCard): void => {
    if (suppressClickRef.current) return
    onOpenCard(card)
  }

  const releaseClickSuppression = (): void => {
    window.setTimeout(() => {
      suppressClickRef.current = false
    }, 0)
  }

  const handleDragStart = (event: DragStartEvent): void => {
    const card = board.draft.find((candidate) => candidate.cardId === event.active.id) ?? null
    setActiveCard(card)
    suppressClickRef.current = true
  }

  const handleDragCancel = (): void => {
    setActiveCard(null)
    releaseClickSuppression()
  }

  const handleDragEnd = (event: DragEndEvent): void => {
    setActiveCard(null)
    releaseClickSuppression()
    const { active, over } = event
    if (!over) return
    const activeId = String(active.id)
    const card = board.draft.find((candidate) => candidate.cardId === activeId)
    if (!card) return
    const overId = String(over.id)
    const targetColumn = resolveDropColumn(board, overId)
    if (targetColumn === 'draft') {
      const visibleCardIds = board.draft.map((draftCard) => draftCard.cardId)
      const nextOrder =
        overId === activeId
          ? null
          : board.draft.some((draftCard) => draftCard.cardId === overId)
            ? reorderDraftCardIds(visibleCardIds, activeId, overId)
            : reorderDraftCardIds(visibleCardIds, activeId, visibleCardIds.at(-1) ?? activeId)
      if (nextOrder) onReorderDrafts(nextOrder)
      return
    }
    if (targetColumn === 'inProgress') {
      void onDispatchDraft(card)
      return
    }
    if (targetColumn === 'done') {
      setNotice(t('kanbanDoneDerivedHint'))
      window.setTimeout(() => setNotice(null), 2400)
    }
  }

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={collisionDetection}
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
      onDragCancel={handleDragCancel}
    >
      {notice ? (
        <div className="px-4 pb-2 text-[12px] text-ds-muted">{notice}</div>
      ) : (
        <div className="px-4 pb-2 text-[12px] text-ds-faint">{t('kanbanBoardDragTip')}</div>
      )}
      <div className="ds-no-drag flex h-full min-h-0 gap-3 overflow-x-auto px-4 pb-4">
        <KanbanColumn
          projectId={board.projectId}
          columnKey="draft"
          cards={board.draft}
          onOpenCard={handleOpenCard}
          onCardContextMenu={onCardContextMenu}
          sortable
          droppable
          activeCard={activeCard}
          onNewCard={onNewTask}
        />
        <KanbanColumn
          projectId={board.projectId}
          columnKey="inProgress"
          cards={board.inProgress}
          onOpenCard={handleOpenCard}
          onCardContextMenu={onCardContextMenu}
          droppable
          activeCard={activeCard}
        />
        <KanbanColumn
          projectId={board.projectId}
          columnKey="done"
          cards={board.done}
          onOpenCard={handleOpenCard}
          onCardContextMenu={onCardContextMenu}
          droppable
          activeCard={activeCard}
        />
      </div>
      <DragOverlay dropAnimation={null}>
        {activeCard ? (
          <KanbanCardView card={activeCard} showColumnLabel={false} isOverlay />
        ) : null}
      </DragOverlay>
    </DndContext>
  )
}
