import { useRef, type ReactNode } from 'react'
import { DndContext, PointerSensor, useDraggable, useSensor, useSensors, type DragMoveEvent } from '@dnd-kit/core'
import { GripVertical } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { CHAT_SPLIT_DRAG_EVENT, finishChatSplitDrag } from '../../lib/chat-split-navigation'

export function ChatSplitDragContext({ children }: { children: ReactNode }) {
  const point = useRef<{ x: number; y: number } | null>(null)
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }))
  const clear = (): void => {
    point.current = null
    window.dispatchEvent(new CustomEvent(CHAT_SPLIT_DRAG_EVENT, { detail: null }))
  }
  const move = (event: DragMoveEvent): void => {
    const origin = event.activatorEvent as PointerEvent
    point.current = { x: origin.clientX + event.delta.x, y: origin.clientY + event.delta.y }
    window.dispatchEvent(new CustomEvent(CHAT_SPLIT_DRAG_EVENT, { detail: { threadId: String(event.active.id), ...point.current } }))
  }
  return <DndContext sensors={sensors} autoScroll={false} onDragMove={move} onDragCancel={clear}
    onDragEnd={event => {
      if (point.current) finishChatSplitDrag(String(event.active.id), point.current.x, point.current.y)
      clear()
    }}>{children}</DndContext>
}

export function ChatSplitDragHandle({ threadId, onMove }: { threadId: string; onMove: (key: string) => void }) {
  const { t } = useTranslation('common')
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({ id: threadId })
  return <button ref={setNodeRef} type="button" className={`ds-chat-split-icon ds-chat-split-grip ${isDragging ? 'is-dragging' : ''}`}
    {...attributes} {...listeners} aria-label={t('splitDragToSwap')} title={t('splitDragToSwap')}
    onKeyDown={event => {
      if (event.key.startsWith('Arrow')) { event.preventDefault(); onMove(event.key) }
      else listeners?.onKeyDown?.(event)
    }}><GripVertical size={14} aria-hidden="true" /></button>
}
