import { useLayoutEffect, useRef, useState, type ReactElement, type ReactNode } from 'react'
import { Plus, Search } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useTranslation } from 'react-i18next'
import type { MarketplaceKind } from '../../store/chat-store'
import type { Notice } from './marketplace-shared'

const KIND_ITEMS: Array<{
  value: MarketplaceKind
  labelKey: 'marketplaceKindMcp' | 'marketplaceKindSkills' | 'marketplaceKindPlugins'
}> = [
  { value: 'mcp', labelKey: 'marketplaceKindMcp' },
  { value: 'skills', labelKey: 'marketplaceKindSkills' },
  { value: 'plugins', labelKey: 'marketplaceKindPlugins' }
]

/** Same pill switcher as before, with an accent thumb so the active kind reads first. */
export function MarketplaceKindSwitch({
  value,
  onChange
}: {
  value: MarketplaceKind
  onChange: (next: MarketplaceKind) => void
}): ReactElement {
  const { t } = useTranslation('common')
  const containerRef = useRef<HTMLDivElement>(null)
  const buttonRefs = useRef(new Map<MarketplaceKind, HTMLButtonElement>())
  const [thumb, setThumb] = useState({ left: 0, width: 0 })

  useLayoutEffect(() => {
    const container = containerRef.current
    const button = buttonRefs.current.get(value)
    if (!container || !button) return
    const update = (): void => {
      setThumb({ left: button.offsetLeft, width: button.offsetWidth })
    }
    update()
    const observer = new ResizeObserver(update)
    observer.observe(container)
    return () => observer.disconnect()
  }, [value])

  return (
    <div
      ref={containerRef}
      role="tablist"
      className="relative inline-flex h-11 shrink-0 items-stretch rounded-full border border-accent/25 bg-accent/[0.06] p-0.5"
    >
      <div
        aria-hidden
        className="ds-marketplace-kind-thumb pointer-events-none absolute top-0.5 bottom-0.5 rounded-full"
        style={{ left: thumb.left, width: thumb.width }}
      />
      {KIND_ITEMS.map((item) => {
        const active = item.value === value
        return (
          <button
            key={item.value}
            ref={(node) => {
              if (node) buttonRefs.current.set(item.value, node)
              else buttonRefs.current.delete(item.value)
            }}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(item.value)}
            className={[
              'relative z-10 flex items-center justify-center rounded-full px-5 text-[13px] font-semibold leading-none tracking-[-0.01em] transition-colors duration-200',
              active ? 'text-white' : 'text-ds-muted hover:text-ds-ink'
            ].join(' ')}
          >
            {t(item.labelKey)}
          </button>
        )
      })}
    </div>
  )
}

export function MarketplaceContentTabs<T extends string>({
  value,
  onChange,
  items,
  trailing
}: {
  value: T
  onChange: (next: T) => void
  items: Array<{ value: T; label: string }>
  trailing?: ReactNode
}): ReactElement {
  return (
    <div className="flex items-end justify-between gap-3 border-b border-ds-border-muted px-5">
      <div className="flex min-w-0 items-stretch" role="tablist">
        {items.map((item) => {
          const active = item.value === value
          return (
            <button
              key={item.value}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => onChange(item.value)}
              className={[
                'relative -mb-px px-3.5 py-3 text-[13px] font-medium tracking-[-0.01em] transition-colors',
                active
                  ? 'text-ds-ink after:absolute after:inset-x-3 after:bottom-0 after:h-0.5 after:rounded-full after:bg-accent'
                  : 'text-ds-muted hover:text-ds-ink'
              ].join(' ')}
            >
              {item.label}
            </button>
          )
        })}
      </div>
      {trailing ? <div className="min-w-0 py-2.5">{trailing}</div> : null}
    </div>
  )
}

export function MarketplaceSearchCreate({
  query,
  onQueryChange,
  placeholder,
  createOpen,
  onCreateToggle,
  createLabel,
  createHostRef
}: {
  query: string
  onQueryChange: (value: string) => void
  placeholder: string
  createOpen: boolean
  onCreateToggle: () => void
  createLabel: string
  createHostRef: (node: HTMLDivElement | null) => void
}): ReactElement {
  return (
    <div className="mt-6 flex flex-wrap items-center gap-3">
      <label className="relative min-w-[16rem] flex-1">
        <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-ds-faint" />
        <input
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          placeholder={placeholder}
          className="ds-ext-search h-11 w-full rounded-2xl border border-ds-border bg-ds-card pl-11 pr-4 text-[15px] text-ds-ink shadow-sm outline-none transition focus:border-accent/40 focus:ring-1 focus:ring-accent/30"
        />
      </label>
      <div className="relative" ref={createHostRef}>
        <button
          type="button"
          onClick={onCreateToggle}
          aria-expanded={createOpen}
          className="inline-flex h-11 items-center justify-center gap-1.5 rounded-2xl border border-ds-border bg-transparent px-3.5 text-[13px] font-medium leading-none text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink"
        >
          <Plus className="h-4 w-4" strokeWidth={1.9} />
          {createLabel}
        </button>
      </div>
    </div>
  )
}

export function stripDocFrontmatter(content: string): string {
  return content.replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n?/, '').trimStart()
}

const drawerMarkdownComponents = {
  table: ({ children }: { children?: ReactNode }) => (
    <div className="ds-marketplace-doc-table-wrap">
      <table>{children}</table>
    </div>
  )
}

export function MarketplaceDocMarkdown({ content }: { content: string }): ReactElement | null {
  const body = stripDocFrontmatter(content)
  if (!body.trim()) return null
  return (
    <article className="ds-marketplace-doc">
      <div className="ds-markdown ds-markdown--document ds-markdown--drawer">
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={drawerMarkdownComponents}>
          {body}
        </ReactMarkdown>
      </div>
    </article>
  )
}

export function NoticeView({ notice }: { notice: Notice }): ReactElement {
  const className =
    notice.tone === 'error'
      ? 'border-red-300/80 bg-red-50 text-red-800 dark:border-red-800/70 dark:bg-red-950/25 dark:text-red-200'
      : notice.tone === 'success'
        ? 'border-emerald-300/80 bg-emerald-50 text-emerald-800 dark:border-emerald-800/70 dark:bg-emerald-950/25 dark:text-emerald-200'
        : 'border-ds-border bg-ds-subtle text-ds-muted'
  return (
    <div className={`mt-4 rounded-xl border px-3 py-2 text-[13px] leading-5 ${className}`}>{notice.message}</div>
  )
}
