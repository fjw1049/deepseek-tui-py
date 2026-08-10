import type { CSSProperties, HTMLAttributes, ReactElement, MouseEvent, ReactNode, Ref } from 'react'
import { useTranslation } from 'react-i18next'
import { GitBranch, GripVertical, Package } from 'lucide-react'
import { formatRelativeTimeLargestUnit } from '../../lib/format-relative-time'
import { KanbanStatusIcon } from './KanbanStatusIcon'
import type { KanbanCard, KanbanColumnKey } from './kanban.logic'

const STATUS_LABEL_KEY: Record<
  KanbanColumnKey,
  'kanbanStatusDraft' | 'kanbanStatusInProgress' | 'kanbanStatusDone'
> = {
  draft: 'kanbanStatusDraft',
  inProgress: 'kanbanStatusInProgress',
  done: 'kanbanStatusDone'
}

export type KanbanCardDragBind = {
  setNodeRef: (node: HTMLElement | null) => void
  style?: CSSProperties
  attributes: HTMLAttributes<HTMLElement>
  listeners: HTMLAttributes<HTMLElement> | undefined
  isDragging: boolean
}

export function KanbanCardView({
  card,
  onOpen,
  onContextMenu,
  showColumnLabel = true,
  isOverlay = false,
  isDragSource = false,
  draggable = false,
  dragBind
}: {
  card: KanbanCard
  onOpen?: (card: KanbanCard) => void
  onContextMenu?: (card: KanbanCard, event: MouseEvent) => void
  showColumnLabel?: boolean
  isOverlay?: boolean
  isDragSource?: boolean
  /** Show grip affordance; pair with dragBind for real DnD. */
  draggable?: boolean
  dragBind?: KanbanCardDragBind
}): ReactElement {
  const { t } = useTranslation('common')
  const timeLabel = card.timestamp ? formatRelativeTimeLargestUnit(card.timestamp) : null
  const dragging = Boolean(dragBind?.isDragging || isDragSource)

  const className = `ds-no-drag group relative flex w-full flex-col gap-3 rounded-2xl border border-ds-border bg-ds-card px-3.5 py-3 text-left transition focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-sky-500/50 ${
    isOverlay
      ? 'shadow-panel rotate-[1.5deg]'
      : dragging
        ? 'opacity-40'
        : 'hover:bg-ds-elevated'
  } ${draggable || dragBind ? 'cursor-grab active:cursor-grabbing' : 'cursor-pointer'}`

  const content: ReactNode = (
    <>
      {draggable || dragBind ? (
        <span
          className="pointer-events-none absolute right-2.5 top-2.5 text-ds-faint opacity-50 group-hover:opacity-100"
          aria-hidden
        >
          <GripVertical className="h-4 w-4" strokeWidth={1.75} />
        </span>
      ) : null}
      <div className="line-clamp-3 pr-6 text-[14px] font-medium leading-5 text-ds-ink">
        {card.title}
      </div>
      <div className="flex min-w-0 items-center gap-2 text-[12px] text-ds-faint">
        <span className="flex min-w-0 flex-1 items-center gap-1.5">
          <Package className="h-3.5 w-3.5 shrink-0 opacity-70" strokeWidth={1.75} aria-hidden />
          {card.branch ? (
            <span className="flex min-w-0 items-center gap-1">
              <GitBranch className="h-3.5 w-3.5 shrink-0 opacity-70" strokeWidth={1.75} aria-hidden />
              <span className="truncate">{card.branch}</span>
            </span>
          ) : null}
        </span>
        <span className="flex shrink-0 items-center gap-1.5">
          {timeLabel ? <span className="tabular-nums">{timeLabel}</span> : null}
          {showColumnLabel ? (
            <span className="flex items-center gap-1">
              <KanbanStatusIcon column={card.column} />
              <span>{t(STATUS_LABEL_KEY[card.column])}</span>
            </span>
          ) : (
            <KanbanStatusIcon column={card.column} />
          )}
        </span>
      </div>
    </>
  )

  // Draggable cards must be a non-<button> surface: Electron/dnd-kit both behave
  // more reliably when the activator node itself owns the pointer listeners.
  if (dragBind) {
    return (
      <div
        ref={dragBind.setNodeRef as Ref<HTMLDivElement>}
        role="button"
        tabIndex={0}
        style={{ touchAction: 'none', ...dragBind.style }}
        className={className}
        {...dragBind.attributes}
        {...dragBind.listeners}
        onClick={
          onOpen
            ? (event) => {
                if (dragBind.isDragging) return
                event.preventDefault()
                onOpen(card)
              }
            : undefined
        }
        onKeyDown={
          onOpen
            ? (event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault()
                  onOpen(card)
                }
              }
            : undefined
        }
        onContextMenu={
          onContextMenu
            ? (event) => {
                event.preventDefault()
                onContextMenu(card, event)
              }
            : undefined
        }
      >
        {content}
      </div>
    )
  }

  return (
    <button
      type="button"
      onClick={onOpen ? () => onOpen(card) : undefined}
      onContextMenu={
        onContextMenu
          ? (event) => {
              event.preventDefault()
              onContextMenu(card, event)
            }
          : undefined
      }
      className={className}
    >
      {content}
    </button>
  )
}
