import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
  type ReactElement,
  type ReactNode
} from 'react'
import { createPortal } from 'react-dom'

type Size = { width: number; height: number }

type Edge = 'n' | 's' | 'e' | 'w' | 'ne' | 'nw' | 'se' | 'sw'

const MIN_WIDTH = 420
const MIN_HEIGHT = 280
const VIEW_PAD = 36

const EDGES: Edge[] = ['n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw']

function defaultSize(): Size {
  if (typeof window === 'undefined') return { width: 1120, height: 760 }
  return {
    width: Math.min(1120, Math.max(MIN_WIDTH, window.innerWidth - VIEW_PAD * 2)),
    height: Math.min(760, Math.max(MIN_HEIGHT, Math.round(window.innerHeight * 0.86)))
  }
}

function clampSize(next: Size): Size {
  const maxW = Math.max(MIN_WIDTH, window.innerWidth - VIEW_PAD * 2)
  const maxH = Math.max(MIN_HEIGHT, window.innerHeight - VIEW_PAD * 2)
  return {
    width: Math.min(maxW, Math.max(MIN_WIDTH, Math.round(next.width))),
    height: Math.min(maxH, Math.max(MIN_HEIGHT, Math.round(next.height)))
  }
}

type Props = {
  open: boolean
  onClose: () => void
  ariaLabel: string
  header: ReactNode
  children: ReactNode
  /** Overlay root class (keeps mermaid/code theme hooks). */
  overlayClassName: string
  panelClassName: string
  bodyClassName: string
  dataAttr?: string
}

export function ResizableFullscreenDialog({
  open,
  onClose,
  ariaLabel,
  header,
  children,
  overlayClassName,
  panelClassName,
  bodyClassName,
  dataAttr
}: Props): ReactElement | null {
  const [size, setSize] = useState<Size>(() => defaultSize())
  const dragRef = useRef<{
    edge: Edge
    startX: number
    startY: number
    startW: number
    startH: number
  } | null>(null)

  useEffect(() => {
    if (!open) return
    setSize(defaultSize())
  }, [open])

  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = prev
    }
  }, [open, onClose])

  useEffect(() => {
    if (!open) return
    const onResize = (): void => {
      setSize((current) => clampSize(current))
    }
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [open])

  const onPointerMove = useCallback((event: PointerEvent) => {
    const drag = dragRef.current
    if (!drag) return
    const dx = event.clientX - drag.startX
    const dy = event.clientY - drag.startY
    let width = drag.startW
    let height = drag.startH
    if (drag.edge.includes('e')) width = drag.startW + dx
    if (drag.edge.includes('w')) width = drag.startW - dx
    if (drag.edge.includes('s')) height = drag.startH + dy
    if (drag.edge.includes('n')) height = drag.startH - dy
    setSize(clampSize({ width, height }))
  }, [])

  const endDrag = useCallback(() => {
    if (!dragRef.current) return
    dragRef.current = null
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
    window.removeEventListener('pointermove', onPointerMove)
    window.removeEventListener('pointerup', endDrag)
    window.removeEventListener('pointercancel', endDrag)
  }, [onPointerMove])

  const startDrag = useCallback(
    (edge: Edge, event: ReactPointerEvent<HTMLSpanElement>) => {
      event.preventDefault()
      event.stopPropagation()
      dragRef.current = {
        edge,
        startX: event.clientX,
        startY: event.clientY,
        startW: size.width,
        startH: size.height
      }
      document.body.style.userSelect = 'none'
      document.body.style.cursor =
        edge === 'n' || edge === 's'
          ? 'ns-resize'
          : edge === 'e' || edge === 'w'
            ? 'ew-resize'
            : edge === 'ne' || edge === 'sw'
              ? 'nesw-resize'
              : 'nwse-resize'
      window.addEventListener('pointermove', onPointerMove)
      window.addEventListener('pointerup', endDrag)
      window.addEventListener('pointercancel', endDrag)
    },
    [endDrag, onPointerMove, size.height, size.width]
  )

  useEffect(
    () => () => {
      window.removeEventListener('pointermove', onPointerMove)
      window.removeEventListener('pointerup', endDrag)
      window.removeEventListener('pointercancel', endDrag)
    },
    [endDrag, onPointerMove]
  )

  if (!open || typeof document === 'undefined') return null

  const panelStyle: CSSProperties = {
    width: size.width,
    height: size.height,
    maxWidth: '100%',
    maxHeight: '100%'
  }

  return createPortal(
    <div
      className={`${overlayClassName} ds-expand-overlay`}
      data-streamdown={dataAttr}
      role="dialog"
      aria-modal="true"
      aria-label={ariaLabel}
      onClick={onClose}
    >
      <div
        className={`${panelClassName} ds-expand-panel`}
        style={panelStyle}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="ds-expand-header">{header}</div>
        <div className={`${bodyClassName} ds-expand-body`}>{children}</div>
        {EDGES.map((edge) => (
          <span
            key={edge}
            className={`ds-expand-handle ds-expand-handle--${edge}`}
            data-edge={edge}
            onPointerDown={(event) => startDrag(edge, event)}
            aria-hidden
          />
        ))}
      </div>
    </div>,
    document.body
  )
}
