import type { CSSProperties, HTMLAttributes, ReactElement, ReactNode, Ref } from 'react'
import {
  DndContext,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
  type UniqueIdentifier
} from '@dnd-kit/core'
import {
  SortableContext,
  useSortable,
  verticalListSortingStrategy
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { moveIdBefore } from '../../lib/sidebar-manual-order'

type SidebarSortableListProps = {
  items: string[]
  disabled?: boolean
  onReorder: (nextIds: string[]) => void
  children: ReactNode
}

/** Vertical sortable list with a 10px activation distance so clicks still select. */
export function SidebarSortableList({
  items,
  disabled = false,
  onReorder,
  children
}: SidebarSortableListProps): ReactElement {
  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: { distance: 10 }
    })
  )

  const handleDragEnd = (event: DragEndEvent): void => {
    const { active, over } = event
    if (!over || active.id === over.id) return
    const activeId = String(active.id)
    const overId = String(over.id)
    if (!items.includes(activeId) || !items.includes(overId)) return
    onReorder(moveIdBefore(items, activeId, overId))
  }

  if (disabled || items.length < 2) {
    return <>{children}</>
  }

  return (
    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
      <SortableContext items={items as UniqueIdentifier[]} strategy={verticalListSortingStrategy}>
        {children}
      </SortableContext>
    </DndContext>
  )
}

type SortableBind = {
  setNodeRef: (node: HTMLElement | null) => void
  style: CSSProperties
  attributes: HTMLAttributes<HTMLElement>
  listeners: ReturnType<typeof useSortable>['listeners']
  isDragging: boolean
}

type SidebarSortableRowProps = {
  id: string
  disabled?: boolean
  className?: string
  children: ReactNode | ((bind: SortableBind) => ReactNode)
}

export function SidebarSortableRow({
  id,
  disabled = false,
  children,
  className
}: SidebarSortableRowProps): ReactElement {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id,
    disabled
  })

  const baseTransform = CSS.Transform.toString(transform)
  const style: CSSProperties = {
    transform: isDragging
      ? `${baseTransform ?? ''} scale(1.02)`.trim()
      : baseTransform || undefined,
    transition,
    zIndex: isDragging ? 20 : undefined,
    position: 'relative'
  }

  if (disabled) {
    if (typeof children === 'function') {
      return (
        <>
          {children({
            setNodeRef: () => undefined,
            style: {},
            attributes: {},
            listeners: undefined,
            isDragging: false
          })}
        </>
      )
    }
    return <div className={className}>{children}</div>
  }

  if (typeof children === 'function') {
    return (
      <>
        {children({
          setNodeRef,
          style,
          attributes: attributes as HTMLAttributes<HTMLElement>,
          listeners,
          isDragging
        })}
      </>
    )
  }

  return (
    <div
      ref={setNodeRef as Ref<HTMLDivElement>}
      style={style}
      className={`ds-sidebar-sortable-row${isDragging ? ' ds-sidebar-sortable-row--dragging' : ''}${
        className ? ` ${className}` : ''
      }`}
      {...attributes}
      {...listeners}
    >
      {children}
    </div>
  )
}
