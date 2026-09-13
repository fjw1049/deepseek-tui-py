import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactElement,
  type ReactNode
} from 'react'
import { createPortal } from 'react-dom'

type Side = 'top' | 'bottom'

type Props = {
  label: string
  children: ReactNode
  side?: Side
  /** Hover dwell before the chip appears (native-title replacement). */
  delayMs?: number
}

/**
 * App-styled tooltip chip replacing slow native `title` tooltips on the
 * high-frequency controls (tree header, tab strip, diff header).
 */
export function Tooltip({
  label,
  children,
  side = 'top',
  delayMs = 350
}: Props): ReactElement {
  const anchorRef = useRef<HTMLSpanElement | null>(null)
  const timerRef = useRef<number | null>(null)
  const [pos, setPos] = useState<{ x: number; y: number; side: Side } | null>(null)

  const clearTimer = useCallback((): void => {
    if (timerRef.current != null) {
      window.clearTimeout(timerRef.current)
      timerRef.current = null
    }
  }, [])

  const hide = useCallback((): void => {
    clearTimer()
    setPos(null)
  }, [clearTimer])

  const show = useCallback(
    (immediate = false): void => {
      clearTimer()
      const run = (): void => {
        const el = anchorRef.current
        if (!el) return
        const rect = el.getBoundingClientRect()
        const x = Math.min(Math.max(rect.left + rect.width / 2, 8), window.innerWidth - 8)
        let resolved: Side = side
        let y = rect.top - 6
        if (side === 'top' && rect.top < 44) {
          resolved = 'bottom'
          y = rect.bottom + 6
        } else if (side === 'bottom' && rect.bottom > window.innerHeight - 44) {
          resolved = 'top'
          y = rect.top - 6
        }
        setPos({ x, y, side: resolved })
      }
      if (immediate) {
        run()
        return
      }
      timerRef.current = window.setTimeout(run, delayMs)
    },
    [clearTimer, delayMs, side]
  )

  useEffect(() => clearTimer, [clearTimer])

  return (
    <span
      ref={anchorRef}
      className="inline-flex shrink-0"
      onMouseEnter={() => show()}
      onMouseLeave={hide}
      onMouseDown={hide}
      onFocus={(event) => {
        if ((event.target as HTMLElement).matches?.(':focus-visible')) show(true)
      }}
      onBlur={hide}
    >
      {children}
      {pos && typeof document !== 'undefined'
        ? createPortal(
            <span
              role="tooltip"
              className="ds-tooltip-chip"
              style={{
                left: pos.x,
                top: pos.y,
                transform: pos.side === 'top' ? 'translate(-50%, -100%)' : 'translate(-50%, 0)'
              }}
            >
              {label}
            </span>,
            document.body
          )
        : null}
    </span>
  )
}
