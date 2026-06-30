import { useLayoutEffect, useRef, useState, type CSSProperties, type ReactElement } from 'react'
import { createPortal } from 'react-dom'
import type { LucideIcon } from 'lucide-react'

export type HoverInfoRow = {
  icon: LucideIcon
  text: string
  /** Render a divider above this row to separate it from the previous group. */
  divider?: boolean
}

type HoverInfoCardProps = {
  anchor: DOMRect
  title: string
  /** Optional icon shown to the left of the title. */
  titleIcon?: LucideIcon
  rows: HoverInfoRow[]
}

const CARD_WIDTH = 248

export function HoverInfoCard({
  anchor,
  title,
  titleIcon: TitleIcon,
  rows
}: HoverInfoCardProps): ReactElement | null {
  const cardRef = useRef<HTMLDivElement | null>(null)
  const [style, setStyle] = useState<CSSProperties>({
    position: 'fixed',
    left: anchor.right + 8,
    top: anchor.top,
    width: CARD_WIDTH,
    zIndex: 125,
    visibility: 'hidden'
  })

  useLayoutEffect(() => {
    const el = cardRef.current
    if (!el) return
    // The app applies `zoom: var(--ds-ui-scale)` to <body>. This card is portaled
    // into <body>, so its fixed `style.top/left` get multiplied by that zoom. The
    // anchor rect (getBoundingClientRect) is already in post-zoom viewport pixels,
    // so divide anchor + viewport bounds by the scale to land in the same space the
    // zoom will then scale back. offsetWidth/Height are layout pixels (pre-zoom),
    // matching that style coordinate space directly.
    const scale =
      parseFloat(
        getComputedStyle(document.documentElement).getPropertyValue('--ds-ui-scale')
      ) || 1
    const cardW = el.offsetWidth
    const cardH = el.offsetHeight
    const aRight = anchor.right / scale
    const aLeft = anchor.left / scale
    const aCenterY = (anchor.top + anchor.height / 2) / scale
    const viewW = window.innerWidth / scale
    const viewH = window.innerHeight / scale
    // Sit to the right of the hovered row, vertically centered on it (the card's
    // midline aligns with the row's midline). Flip to the left when there is no
    // room on the right.
    let left = aRight + 8
    if (left + cardW > viewW - 8) {
      left = Math.max(8, aLeft - cardW - 8)
    }
    const desiredTop = aCenterY - cardH / 2
    const top = Math.max(8, Math.min(desiredTop, viewH - cardH - 8))
    setStyle({ position: 'fixed', left, top, width: CARD_WIDTH, zIndex: 125 })
  }, [anchor])

  const card = (
    <div
      ref={cardRef}
      style={style}
      className="ds-no-drag pointer-events-none overflow-hidden rounded-2xl border border-ds-border bg-ds-elevated p-1.5 shadow-[0_24px_70px_rgba(44,55,78,0.18)] backdrop-blur-xl dark:shadow-[0_30px_80px_rgba(0,0,0,0.42)]"
    >
      <div className="flex h-8 items-center gap-2.5 rounded-lg px-2.5">
        {TitleIcon ? (
          <TitleIcon className="h-4 w-4 shrink-0 text-ds-faint" strokeWidth={1.8} />
        ) : null}
        <span className="min-w-0 flex-1 truncate text-[13.5px] font-medium leading-none text-ds-ink">
          {title}
        </span>
      </div>
      {rows.map((row, index) => {
        const Icon = row.icon
        return (
          <div key={`${index}-${row.text}`}>
            {row.divider ? <div className="mx-1 my-1 h-px bg-ds-border-muted/50" /> : null}
            <div className="flex h-8 items-center gap-2.5 rounded-lg px-2.5 text-[13px] leading-none text-ds-muted">
              <Icon className="h-4 w-4 shrink-0 text-ds-faint" strokeWidth={1.8} />
              <span className="min-w-0 truncate">{row.text}</span>
            </div>
          </div>
        )
      })}
    </div>
  )

  if (typeof document === 'undefined') return null
  return createPortal(card, document.body)
}
