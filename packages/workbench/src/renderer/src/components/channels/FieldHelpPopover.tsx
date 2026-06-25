import { useEffect, useRef, useState, type ReactElement, type ReactNode } from 'react'
import { CircleHelp } from 'lucide-react'

type Props = {
  title: string
  intro?: string
  steps?: string[]
  children?: ReactNode
  ariaLabel?: string
}

const SHOW_DELAY_MS = 120
const HIDE_DELAY_MS = 160

export function FieldHelpPopover({
  title,
  intro,
  steps = [],
  children,
  ariaLabel
}: Props): ReactElement {
  const [open, setOpen] = useState(false)
  const showTimerRef = useRef<number | null>(null)
  const hideTimerRef = useRef<number | null>(null)

  const clearTimers = (): void => {
    if (showTimerRef.current !== null) {
      window.clearTimeout(showTimerRef.current)
      showTimerRef.current = null
    }
    if (hideTimerRef.current !== null) {
      window.clearTimeout(hideTimerRef.current)
      hideTimerRef.current = null
    }
  }

  const scheduleShow = (): void => {
    if (hideTimerRef.current !== null) {
      window.clearTimeout(hideTimerRef.current)
      hideTimerRef.current = null
    }
    if (open || showTimerRef.current !== null) return
    showTimerRef.current = window.setTimeout(() => {
      showTimerRef.current = null
      setOpen(true)
    }, SHOW_DELAY_MS)
  }

  const scheduleHide = (): void => {
    if (showTimerRef.current !== null) {
      window.clearTimeout(showTimerRef.current)
      showTimerRef.current = null
    }
    if (!open) return
    hideTimerRef.current = window.setTimeout(() => {
      hideTimerRef.current = null
      setOpen(false)
    }, HIDE_DELAY_MS)
  }

  useEffect(() => () => clearTimers(), [])

  return (
    <span
      className="relative inline-flex shrink-0 align-middle"
      onMouseEnter={scheduleShow}
      onMouseLeave={scheduleHide}
      onFocus={scheduleShow}
      onBlur={scheduleHide}
    >
      <span
        role="img"
        aria-label={ariaLabel ?? title}
        tabIndex={0}
        className="inline-flex h-5 w-5 cursor-default items-center justify-center rounded-full text-ds-faint transition hover:bg-ds-hover/80 hover:text-ds-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
      >
        <CircleHelp className="h-3.5 w-3.5" />
      </span>

      {open ? (
        <div
          role="tooltip"
          aria-label={ariaLabel ?? title}
          className="absolute bottom-full left-full z-[120] w-[min(280px,calc(100vw-32px))] pb-1 pl-0.5"
        >
          <div className="rounded-xl border border-ds-border/70 bg-ds-card/92 px-3.5 py-3 text-[12px] leading-[1.55] text-ds-ink shadow-[0_12px_32px_rgba(15,23,42,0.12)] backdrop-blur-md dark:border-white/10 dark:bg-ds-elevated/94 dark:shadow-[0_14px_36px_rgba(0,0,0,0.34)]">
            <p className="text-[13px] font-medium text-ds-ink">{title}</p>
            {intro ? <p className="mt-1.5 text-ds-muted">{intro}</p> : null}
            {steps.length > 0 ? (
              <ol className={`list-decimal space-y-1 pl-4 text-ds-ink/90 ${intro ? 'mt-2' : 'mt-1.5'}`}>
                {steps.map((step) => (
                  <li key={step}>{step}</li>
                ))}
              </ol>
            ) : null}
            {children ? <div className={intro || steps.length > 0 ? 'mt-2' : 'mt-1.5'}>{children}</div> : null}
          </div>
        </div>
      ) : null}
    </span>
  )
}
