import { useEffect, useLayoutEffect, useRef, type RefObject } from 'react'
import type { ChatLayout } from '../store/chat-layout-store'

/** Move stable pane hosts from their current visual position with an interruptible spring. */
export function usePaneSwapMotion(root: RefObject<HTMLDivElement | null>, layout: ChatLayout, narrow: boolean): void {
  const previous = useRef(new Map<string, DOMRect>())
  const order = layout.panes.map(pane => pane.id).join(',')
  const previousOrder = useRef(order)
  const motion = useRef(new Map<HTMLElement, { x: number; y: number; vx: number; vy: number }>())
  const frame = useRef(0)
  useEffect(() => () => {
    cancelAnimationFrame(frame.current)
    for (const element of motion.current.keys()) element.style.transform = ''
  }, [])
  useLayoutEffect(() => {
    if (order === previousOrder.current && !narrow && motion.current.size) return
    const elements = [...(root.current?.querySelectorAll<HTMLElement>('[data-chat-pane]') ?? [])]
    const moved = order !== previousOrder.current && !narrow && !window.matchMedia('(prefers-reduced-motion: reduce)').matches
    previousOrder.current = order
    cancelAnimationFrame(frame.current)
    const next = new Map<string, DOMRect>()
    for (const element of elements) {
      const id = element.dataset.chatPane!
      const old = previous.current.get(id)
      const current = motion.current.get(element)
      element.style.transform = ''
      const rect = element.getBoundingClientRect()
      next.set(id, rect)
      if (moved && old) {
        const scale = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--ds-ui-scale')) || 1
        const x = (old.left - rect.left) / scale + (current?.x ?? 0)
        const y = (old.top - rect.top) / scale + (current?.y ?? 0)
        if (Math.abs(x) + Math.abs(y) > .5) {
          motion.current.set(element, { x, y, vx: current?.vx ?? 0, vy: current?.vy ?? 0 })
          element.style.transform = `translate3d(${x}px, ${y}px, 0)`
          continue
        }
      }
      motion.current.delete(element)
    }
    for (const element of motion.current.keys()) if (!element.isConnected) motion.current.delete(element)
    previous.current = next
    let last = performance.now()
    const tick = (now: number): void => {
      const dt = Math.min((now - last) / 1000, .025)
      last = now
      for (const [element, value] of motion.current) {
        value.vx += (-400 * value.x - 40 * value.vx) * dt
        value.vy += (-400 * value.y - 40 * value.vy) * dt
        value.x += value.vx * dt; value.y += value.vy * dt
        if (Math.abs(value.x) + Math.abs(value.y) + Math.abs(value.vx) + Math.abs(value.vy) < .5) {
          element.style.transform = ''; motion.current.delete(element)
        } else element.style.transform = `translate3d(${value.x}px, ${value.y}px, 0)`
      }
      if (motion.current.size) frame.current = requestAnimationFrame(tick)
    }
    if (motion.current.size) frame.current = requestAnimationFrame(tick)
  }, [root, order, layout.x, layout.y, layout.arrangement, narrow])
}
