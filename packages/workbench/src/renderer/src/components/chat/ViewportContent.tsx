import { enqueueViewportRender } from './viewport-render-queue'
import { useEffect, useRef, useState, type ReactNode } from 'react'

/** Keep measured space while expensive offscreen message content is unmounted. */
export function ViewportContent({ children, active = false }: { children: ReactNode; active?: boolean }) {
  const ref = useRef<HTMLDivElement>(null)
  const height = useRef(160)
  const [visible, setVisible] = useState(typeof IntersectionObserver === 'undefined')
  useEffect(() => {
    const node = ref.current
    if (!node || typeof IntersectionObserver === 'undefined') return
    let cancelPending = (): void => {}
    const observer = new IntersectionObserver(([entry]) => {
      if (!entry) return
      cancelPending()
      if (entry.isIntersecting) cancelPending = enqueueViewportRender(() => setVisible(true))
      else setVisible(false)
    }, { root: node.closest('.ds-scroll-surface'), rootMargin: '800px' })
    observer.observe(node)
    return () => { cancelPending(); observer.disconnect() }
  }, [])
  useEffect(() => {
    const node = ref.current
    if (!node || !(visible || active) || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(([entry]) => {
      if (entry) height.current = entry.borderBoxSize?.[0]?.blockSize ?? entry.contentRect.height
    })
    observer.observe(node)
    return () => observer.disconnect()
  }, [visible, active])
  return <div ref={ref} style={visible || active ? undefined : { height: height.current }}>
    {visible || active ? children : null}
  </div>
}
