import type { CSSProperties, ReactElement } from 'react'
import { useEffect, useRef, useState } from 'react'
import { threadMarqueeDurationMs } from '../lib/thread-marquee'

type HoverMarqueeTextProps = {
  active?: boolean
  className: string
  style?: CSSProperties
  text: string
  title: string
}

const MARQUEE_DWELL_MS = 320

export function HoverMarqueeText({
  active = false,
  className,
  style,
  text,
  title
}: HoverMarqueeTextProps): ReactElement {
  const viewportRef = useRef<HTMLSpanElement>(null)
  const textRef = useRef<HTMLSpanElement>(null)
  const animationRef = useRef<Animation | null>(null)
  const dwellTimerRef = useRef<number | null>(null)
  const frameRef = useRef<number | null>(null)
  const previousTextRef = useRef(text)
  const [hovered, setHovered] = useState(false)
  const isActive = active || hovered
  const [expanded, setExpanded] = useState(false)
  const [overflowing, setOverflowing] = useState(false)
  const expandedRef = useRef(false)

  useEffect(() => {
    const viewport = viewportRef.current
    const inner = textRef.current
    if (!viewport || !inner) return
    const measure = (): void => setOverflowing(inner.scrollWidth > viewport.clientWidth + 1)
    const observer = new ResizeObserver(measure)
    observer.observe(viewport)
    observer.observe(inner)
    measure()
    return () => observer.disconnect()
  }, [text])

  const updateExpanded = (next: boolean): void => {
    expandedRef.current = next
    setExpanded(next)
  }

  const clearSchedule = (): void => {
    if (dwellTimerRef.current != null) {
      window.clearTimeout(dwellTimerRef.current)
      dwellTimerRef.current = null
    }
    if (frameRef.current != null) {
      window.cancelAnimationFrame(frameRef.current)
      frameRef.current = null
    }
  }

  useEffect(() => {
    const inner = textRef.current
    const viewport = viewportRef.current
    if (!inner || !viewport) return

    clearSchedule()
    const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true
    if (previousTextRef.current !== text) {
      previousTextRef.current = text
      animationRef.current?.cancel()
      animationRef.current = null
      updateExpanded(false)
    }

    if (!isActive || reduceMotion) {
      const currentTransform = window.getComputedStyle(inner).transform
      animationRef.current?.cancel()
      animationRef.current = null
      if (!expandedRef.current || reduceMotion || currentTransform === 'none') {
        updateExpanded(false)
        return
      }
      const reset = inner.animate(
        [
          { transform: currentTransform },
          { transform: 'translateX(0)' }
        ],
        { duration: 180, easing: 'ease-out' }
      )
      animationRef.current = reset
      reset.onfinish = () => {
        if (animationRef.current !== reset) return
        reset.cancel()
        animationRef.current = null
        updateExpanded(false)
      }
      return
    }

    dwellTimerRef.current = window.setTimeout(() => {
      updateExpanded(true)
      frameRef.current = window.requestAnimationFrame(() => {
        frameRef.current = null
        const overflow = Math.ceil(inner.scrollWidth - viewport.clientWidth)
        if (overflow <= 1) {
          updateExpanded(false)
          return
        }
        const currentTransform = window.getComputedStyle(inner).transform
        const previousAnimation = animationRef.current
        if (previousAnimation) previousAnimation.onfinish = null
        previousAnimation?.cancel()
        const marquee = inner.animate(
          [
            { transform: currentTransform === 'none' ? 'translateX(0)' : currentTransform },
            { transform: `translateX(-${overflow}px)` }
          ],
          {
            duration: threadMarqueeDurationMs(overflow),
            easing: 'linear',
            fill: 'forwards'
          }
        )
        animationRef.current = marquee
      })
    }, MARQUEE_DWELL_MS)
  }, [isActive, text])

  useEffect(
    () => () => {
      clearSchedule()
      animationRef.current?.cancel()
    },
    []
  )

  return (
    <span
      ref={viewportRef}
      className={`${className} overflow-hidden whitespace-nowrap ${overflowing && !expanded ? 'ds-sidebar-title-fade' : ''}`}
      style={style}
      title={title}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <span
        ref={textRef}
        className="inline-block w-max max-w-none whitespace-nowrap"
      >
        {text}
      </span>
    </span>
  )
}

