import { useLayoutEffect, useRef, useState, type ReactElement } from 'react'

type Item<T extends string> = {
  value: T
  label: string
}

type Props<T extends string> = {
  value: T
  onChange: (value: T) => void
  items: Item<T>[]
  className?: string
  segmentClassName?: string
}

export function GlassSegmentedControl<T extends string>({
  value,
  onChange,
  items,
  className = '',
  segmentClassName = 'px-3 py-1.5'
}: Props<T>): ReactElement {
  const containerRef = useRef<HTMLDivElement>(null)
  const buttonRefs = useRef(new Map<T, HTMLButtonElement>())
  const [hovered, setHovered] = useState<T | null>(null)
  const [thumb, setThumb] = useState({ left: 0, width: 0 })

  const highlight = hovered ?? value
  const stretch = /\bw-full\b/.test(className)

  useLayoutEffect(() => {
    const container = containerRef.current
    const button = buttonRefs.current.get(highlight)
    if (!container || !button) return

    const update = (): void => {
      setThumb({
        left: button.offsetLeft,
        width: button.offsetWidth
      })
    }

    update()
    const observer = new ResizeObserver(update)
    observer.observe(container)
    return () => observer.disconnect()
  }, [highlight, items, stretch])

  return (
    <div
      ref={containerRef}
      className={[
        stretch
          ? 'relative flex h-10 w-full min-w-0 items-stretch rounded-full border border-ds-border/70 bg-ds-elevated/45 p-0.5'
          : 'relative inline-flex h-10 shrink-0 items-stretch rounded-full border border-ds-border/70 bg-ds-elevated/45 p-0.5',
        className
      ].join(' ')}
      onMouseLeave={() => setHovered(null)}
    >
      <div
        aria-hidden
        className="ds-glass-segment-thumb pointer-events-none absolute top-0.5 bottom-0.5 rounded-full"
        style={{ left: thumb.left, width: thumb.width }}
      />
      {items.map((item) => (
        <button
          key={item.value}
          ref={(node) => {
            if (node) buttonRefs.current.set(item.value, node)
            else buttonRefs.current.delete(item.value)
          }}
          type="button"
          onClick={() => onChange(item.value)}
          onMouseEnter={() => setHovered(item.value)}
          onFocus={() => setHovered(item.value)}
          onBlur={() => setHovered(null)}
          className={[
            'relative z-10 flex items-center justify-center rounded-full text-center text-[12px] font-medium leading-none transition-colors duration-200',
            stretch ? 'min-w-0 flex-1' : 'shrink-0',
            segmentClassName,
            value === item.value ? 'text-ds-ink' : 'text-ds-muted hover:text-ds-ink'
          ].join(' ')}
        >
          {item.label}
        </button>
      ))}
    </div>
  )
}
