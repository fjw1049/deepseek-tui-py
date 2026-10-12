import { useEffect, useLayoutEffect, useRef, useState, type ReactElement, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

const ACTION_WIDTH = 76

export function ActivitySwipeRow({ children, selected, title, open, onOpenChange, onSelect, onDismiss }: {
  children: ReactNode
  selected: boolean
  title: string
  open: boolean
  onOpenChange: (open: boolean) => void
  onSelect: () => void
  onDismiss: () => void
}): ReactElement {
  const { t } = useTranslation('common')
  const shell = useRef<HTMLDivElement>(null)
  const row = useRef<HTMLButtonElement>(null)
  const gesture = useRef<{ id: number; x: number; y: number; start: number; horizontal: boolean; lastX: number; lastTime: number; velocity: number } | null>(null)
  const suppressClick = useRef(false)
  const [dragOffset, setDragOffset] = useState<number | null>(null)
  const [dismissing, setDismissing] = useState(false)
  const animation = useRef<Animation | null>(null)
  const openChange = useRef(onOpenChange)
  useLayoutEffect(() => { openChange.current = onOpenChange }, [onOpenChange])
  const offset = dragOffset ?? (open ? -ACTION_WIDTH : 0)
  const clamp = (value: number): number => Math.max(-ACTION_WIDTH, Math.min(0, value))
  const liveOffset = (): number => {
    const transform = row.current ? getComputedStyle(row.current).transform : 'none'
    return transform && transform !== 'none' ? new DOMMatrixReadOnly(transform).m41 : 0
  }

  useEffect(() => () => animation.current?.cancel(), [])

  useEffect(() => {
    const element = shell.current
    if (!element || dismissing) return
    let position: number | null = null
    let timer: ReturnType<typeof setTimeout>
    const onWheel = (event: WheelEvent): void => {
      if (Math.abs(event.deltaX) <= Math.abs(event.deltaY) || event.ctrlKey) return
      event.preventDefault()
      suppressClick.current = true
      const delta = event.deltaX * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? ACTION_WIDTH : 1)
      position = clamp((position ?? liveOffset()) - delta)
      setDragOffset(position)
      clearTimeout(timer)
      timer = setTimeout(() => {
        openChange.current(position! < -ACTION_WIDTH / 2)
        setDragOffset(null)
        position = null
      }, 100)
    }
    element.addEventListener('wheel', onWheel, { passive: false })
    return () => { element.removeEventListener('wheel', onWheel); clearTimeout(timer) }
  }, [dismissing])

  const dismiss = async (): Promise<void> => {
    if (dismissing) return
    setDismissing(true)
    if (shell.current && !window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      animation.current = shell.current.animate([
        { height: `${shell.current.offsetHeight}px`, opacity: 1 },
        { height: '0px', opacity: 0 }
      ], { duration: 180, easing: 'cubic-bezier(.2,.8,.2,1)', fill: 'forwards' })
      try { await animation.current.finished } catch { return }
    }
    onDismiss()
  }

  return <div ref={shell} className={`ds-activity-swipe ${dismissing ? 'ds-activity-swipe--dismissing' : ''} ${dragOffset !== null ? 'ds-activity-swipe--dragging' : ''}`}>
    <button type="button" className="ds-activity-dismiss" disabled={dismissing}
      style={{ clipPath: `inset(0 0 0 ${ACTION_WIDTH + offset}px)`, pointerEvents: open ? 'auto' : 'none' }}
      aria-label={`${t('activityDismiss')} · ${title}`}
      onFocus={() => onOpenChange(true)} onClick={() => void dismiss()}>{t('activityDismiss')}</button>
    <button ref={row} type="button"
      className={`ds-activity-row ${selected ? 'ds-activity-row--selected' : ''} ${dragOffset !== null ? 'ds-activity-row--dragging' : ''}`}
      style={{ transform: `translateX(${offset}px)` }}
      aria-current={selected ? 'page' : undefined} title={`${title} · ${t('activitySwipeHint')}`}
      disabled={dismissing}
      onPointerDown={(event) => {
        if (event.button !== 0 || !event.isPrimary) return
        suppressClick.current = false
        gesture.current = { id: event.pointerId, x: event.clientX, y: event.clientY, start: liveOffset(), horizontal: false, lastX: event.clientX, lastTime: event.timeStamp, velocity: 0 }
      }}
      onPointerMove={(event) => {
        const drag = gesture.current
        if (!drag || drag.id !== event.pointerId) return
        const dx = event.clientX - drag.x
        const dy = event.clientY - drag.y
        if (!drag.horizontal) {
          if (Math.max(Math.abs(dx), Math.abs(dy)) < 8) return
          if (Math.abs(dy) >= Math.abs(dx)) { gesture.current = null; return }
          drag.horizontal = true
          suppressClick.current = true
          event.currentTarget.setPointerCapture(event.pointerId)
        }
        const elapsed = event.timeStamp - drag.lastTime
        if (elapsed > 0) drag.velocity = (event.clientX - drag.lastX) / elapsed
        drag.lastX = event.clientX
        drag.lastTime = event.timeStamp
        setDragOffset(clamp(drag.start + dx))
      }}
      onPointerUp={(event) => {
        const drag = gesture.current
        if (!drag || drag.id !== event.pointerId) return
        gesture.current = null
        if (drag.horizontal) {
          const velocity = event.timeStamp - drag.lastTime < 100 ? drag.velocity : 0
          onOpenChange(clamp(drag.start + event.clientX - drag.x + velocity * 120) < -ACTION_WIDTH / 2)
          setDragOffset(null)
          event.currentTarget.releasePointerCapture(event.pointerId)
        }
      }}
      onPointerCancel={() => { gesture.current = null; setDragOffset(null) }}
      onLostPointerCapture={() => { gesture.current = null; setDragOffset(null) }}
      onKeyDown={(event) => {
        if (event.key === 'ArrowLeft' || event.key === 'ArrowRight' || event.key === 'Escape') {
          event.preventDefault()
          onOpenChange(event.key === 'ArrowLeft')
        }
      }}
      onContextMenu={(event) => { event.preventDefault(); onOpenChange(true) }}
      onClick={(event) => {
        if (suppressClick.current && event.detail !== 0) { suppressClick.current = false; return }
        if (open) onOpenChange(false)
        else onSelect()
      }}>{children}</button>
  </div>
}
