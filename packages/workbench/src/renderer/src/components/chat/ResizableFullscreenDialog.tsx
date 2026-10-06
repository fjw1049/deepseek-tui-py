import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useId,
  useRef,
  useState,
  type CSSProperties,
  type MouseEvent as ReactMouseEvent,
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
/** Ignore backdrop dismiss briefly after open (avoids the opening click closing us). */
const BACKDROP_ARM_MS = 280

const EDGES: Edge[] = ['n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw']

/** Open expand dialogs, bottom → top. Escape closes only the topmost. */
const openStack: string[] = []
let bodyOverflowBeforeDialogs = ''

function uiScale(): number {
  const value = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--ds-ui-scale'))
  return Number.isFinite(value) && value > 0 ? value : 1
}

function defaultSize(): Size {
  if (typeof window === 'undefined') return { width: 1120, height: 760 }
  return clampSize({ width: 1120, height: Math.min(760, Math.round(window.innerHeight / uiScale() * 0.86)) })
}

function clampSize(next: Size): Size {
  const maxW = Math.max(0, window.innerWidth / uiScale() - VIEW_PAD * 2)
  const maxH = Math.max(0, window.innerHeight / uiScale() - VIEW_PAD * 2)
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
  const dialogId = useId()
  const bodyRef = useRef<HTMLDivElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState<Size>(() => defaultSize())
  const [stackDepth, setStackDepth] = useState(0)
  const armedRef = useRef(false)
  const dragRef = useRef<{
    edge: Edge
    startX: number
    startY: number
    startW: number
    startH: number
    cursor: string
    userSelect: string
  } | null>(null)

  useLayoutEffect(() => {
    if (!open) return
    const el = bodyRef.current
    if (el) el.scrollTop = 0
  }, [open])

  useEffect(() => {
    if (!open) return
    setSize(defaultSize())
    armedRef.current = false
    const armTimer = window.setTimeout(() => {
      armedRef.current = true
    }, BACKDROP_ARM_MS)
    if (openStack.length === 0) bodyOverflowBeforeDialogs = document.body.style.overflow
    openStack.push(dialogId)
    setStackDepth(openStack.length)

    const previousFocus = document.activeElement as HTMLElement | null
    panelRef.current?.focus()
    const onKey = (event: KeyboardEvent): void => {
      if (openStack[openStack.length - 1] !== dialogId) return
      if (event.key === 'Escape') {
        event.preventDefault()
        event.stopPropagation()
        onClose()
      }
      if (event.key === 'Tab') {
        const panel = panelRef.current
        const controls = Array.from(panel?.querySelectorAll<HTMLElement>(
          'button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])'
        ) ?? []).filter((node) => !node.closest('[hidden], [inert]') && getComputedStyle(node).display !== 'none')
        const first = controls[0]
        const last = controls[controls.length - 1]
        if (!first || document.activeElement === panel || !panel?.contains(document.activeElement) ||
          (event.shiftKey ? document.activeElement === first : document.activeElement === last)) {
          event.preventDefault()
          ;((event.shiftKey ? last : first) ?? panel)?.focus()
        }
      }
    }
    window.addEventListener('keydown', onKey, true)
    document.body.style.overflow = 'hidden'

    return () => {
      window.clearTimeout(armTimer)
      window.removeEventListener('keydown', onKey, true)
      const wasTop = openStack[openStack.length - 1] === dialogId
      const index = openStack.lastIndexOf(dialogId)
      if (index >= 0) openStack.splice(index, 1)
      if (openStack.length === 0) document.body.style.overflow = bodyOverflowBeforeDialogs
      armedRef.current = false
      if (wasTop && previousFocus?.isConnected) previousFocus.focus()
    }
  }, [dialogId, open, onClose])

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
    // The panel stays centered, so each edge moves by half the size change.
    const dx = (event.clientX - drag.startX) * 2 / uiScale()
    const dy = (event.clientY - drag.startY) * 2 / uiScale()
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
    const drag = dragRef.current
    dragRef.current = null
    document.body.style.cursor = drag.cursor
    document.body.style.userSelect = drag.userSelect
    window.removeEventListener('pointermove', onPointerMove)
    window.removeEventListener('pointerup', endDrag)
    window.removeEventListener('pointercancel', endDrag)
    window.removeEventListener('blur', endDrag)
  }, [onPointerMove])

  const startDrag = useCallback(
    (edge: Edge, event: ReactPointerEvent<HTMLSpanElement>) => {
      if (event.button !== 0) return
      endDrag()
      event.preventDefault()
      event.stopPropagation()
      dragRef.current = {
        edge,
        startX: event.clientX,
        startY: event.clientY,
        startW: size.width,
        startH: size.height,
        cursor: document.body.style.cursor,
        userSelect: document.body.style.userSelect
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
      window.addEventListener('blur', endDrag)
    },
    [endDrag, onPointerMove, size.height, size.width]
  )

  useEffect(() => {
    if (!open) endDrag()
    return endDrag
  }, [endDrag, open])

  const onBackdropMouseDown = (event: ReactMouseEvent<HTMLDivElement>): void => {
    // Only dismiss when pressing the dimmed backdrop itself — not children.
    // Avoids click bubbling from nested Maximize buttons closing the parent.
    if (event.target !== event.currentTarget) return
    if (!armedRef.current) return
    onClose()
  }

  if (!open || typeof document === 'undefined') return null

  const panelStyle: CSSProperties = {
    width: size.width,
    height: size.height,
    maxWidth: '100%',
    maxHeight: '100%'
  }

  return createPortal(
    <div
      className={`${overlayClassName} ds-expand-overlay ds-no-drag`}
      data-streamdown={dataAttr}
      role="dialog"
      aria-modal="true"
      aria-label={ariaLabel}
      style={{ zIndex: 9999 + stackDepth }}
      onMouseDown={onBackdropMouseDown}
    >
      <div
        ref={panelRef}
        tabIndex={-1}
        className={`${panelClassName} ds-expand-panel`}
        style={panelStyle}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="ds-expand-header">{header}</div>
        <div ref={bodyRef} className={`${bodyClassName} ds-expand-body`}>{children}</div>
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
