import { useEffect, useRef, useState, type CSSProperties, type ReactElement, type MouseEvent } from 'react'
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
import {
  beginLightDismissShell,
  endLightDismissShell
} from '../../hooks/use-light-dismiss'
import { KanbanCardView } from './KanbanCardView'
import { KanbanColumn } from './KanbanColumn'
import {
  adjustKanbanOverlayForUiScale,
  layoutPxFromVisual,
  readKanbanUiScale
} from './kanban-drag-coords'
import {
  cardsForColumn,
  findBoardCard,
  parseKanbanColumnDropId,
  reorderKanbanCardIds,
  type KanbanCard,
  type KanbanColumnKey,
  type KanbanProjectBoard
} from './kanban.logic'

function resolveDropColumn(board: KanbanProjectBoard, overId: string): KanbanColumnKey | null {
  const columnDrop = parseKanbanColumnDropId(overId)
  if (columnDrop) {
    return columnDrop.projectId === board.projectId ? columnDrop.column : null
  }
  const overCard = findBoardCard(board, overId)
  return overCard?.column ?? null
}

const collisionDetection: CollisionDetection = (args) => {
  const pointerCollisions = pointerWithin(args)
  if (pointerCollisions.length > 0) return pointerCollisions
  return closestCorners(args)
}

function overlayBoxFromRect(rect: { top: number; left: number; width: number; height: number }): CSSProperties {
  const scale = readKanbanUiScale()
  return {
    top: layoutPxFromVisual(rect.top, scale),
    left: layoutPxFromVisual(rect.left, scale),
    width: layoutPxFromVisual(rect.width, scale),
    height: layoutPxFromVisual(rect.height, scale)
  }
}

export function KanbanProjectBoardView({
  board,
  onOpenCard,
  onCardContextMenu,
  onNewTask,
  onReorderColumn,
  onDispatchDraft
}: {
  board: KanbanProjectBoard
  onOpenCard: (card: KanbanCard) => void
  onCardContextMenu?: (card: KanbanCard, event: MouseEvent) => void
  onNewTask: () => void
  onReorderColumn: (column: KanbanColumnKey, cardIds: string[]) => void
  onDispatchDraft: (card: KanbanCard) => void | Promise<void>
}): ReactElement {
  const { t } = useTranslation('common')
  const [activeCard, setActiveCard] = useState<KanbanCard | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const suppressClickRef = useRef(false)
  const shellUnlockedRef = useRef(false)
  const overlayBoxRef = useRef<CSSProperties>({})

  const sensors = useSensors(
    useSensor(PointerSensor, {
      // Keep clicks working; start drag after a short move.
      activationConstraint: { distance: 8 }
    })
  )

  const unlockShell = (): void => {
    if (shellUnlockedRef.current) return
    shellUnlockedRef.current = true
    beginLightDismissShell()
  }

  const relockShell = (): void => {
    if (!shellUnlockedRef.current) return
    shellUnlockedRef.current = false
    endLightDismissShell()
  }

  useEffect(() => () => relockShell(), [])

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
    const card = findBoardCard(board, String(event.active.id))
    const rect = event.active.rect.current.initial ?? event.active.rect.current.translated
    overlayBoxRef.current = rect ? overlayBoxFromRect(rect) : {}
    setActiveCard(card)
    suppressClickRef.current = true
    unlockShell()
  }

  const handleDragCancel = (): void => {
    setActiveCard(null)
    overlayBoxRef.current = {}
    releaseClickSuppression()
    relockShell()
  }

  const reorderWithin = (column: KanbanColumnKey, activeId: string, overId: string): void => {
    const visibleCardIds = cardsForColumn(board, column).map((card) => card.cardId)
    const nextOrder =
      overId === activeId
        ? null
        : visibleCardIds.includes(overId)
          ? reorderKanbanCardIds(visibleCardIds, activeId, overId)
          : reorderKanbanCardIds(visibleCardIds, activeId, visibleCardIds.at(-1) ?? activeId)
    if (nextOrder) onReorderColumn(column, nextOrder)
  }

  const handleDragEnd = (event: DragEndEvent): void => {
    setActiveCard(null)
    overlayBoxRef.current = {}
    releaseClickSuppression()
    relockShell()
    const { active, over } = event
    if (!over) return
    const activeId = String(active.id)
    const card = findBoardCard(board, activeId)
    if (!card) return
    const overId = String(over.id)
    const targetColumn = resolveDropColumn(board, overId)
    if (!targetColumn) return

    if (targetColumn === card.column) {
      reorderWithin(targetColumn, activeId, overId)
      return
    }

    // Cross-column: only Draft → In Progress dispatches a send.
    if (card.column === 'draft' && targetColumn === 'inProgress') {
      void onDispatchDraft(card)
      return
    }
    if (card.column === 'draft' && targetColumn === 'done') {
      setNotice(t('kanbanDoneDerivedHint'))
      window.setTimeout(() => setNotice(null), 2400)
      return
    }

    setNotice(t('kanbanStatusDerivedHint'))
    window.setTimeout(() => setNotice(null), 2400)
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
        <div className="px-8 pb-2 text-[12px] text-ds-muted">{notice}</div>
      ) : (
        <div className="px-8 pb-2 text-[12px] text-ds-faint">{t('kanbanBoardDragTip')}</div>
      )}
      <div className="ds-no-drag flex h-full min-h-0 gap-5 overflow-x-auto px-8 pb-6">
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
          sortable
          droppable
          activeCard={activeCard}
        />
        <KanbanColumn
          projectId={board.projectId}
          columnKey="done"
          cards={board.done}
          onOpenCard={handleOpenCard}
          onCardContextMenu={onCardContextMenu}
          sortable
          droppable
          activeCard={activeCard}
        />
      </div>
      <DragOverlay
        dropAnimation={null}
        className="ds-no-drag"
        modifiers={[adjustKanbanOverlayForUiScale]}
        style={activeCard ? overlayBoxRef.current : undefined}
      >
        {activeCard ? (
          <KanbanCardView card={activeCard} showColumnLabel={false} isOverlay />
        ) : null}
      </DragOverlay>
    </DndContext>
  )
}
