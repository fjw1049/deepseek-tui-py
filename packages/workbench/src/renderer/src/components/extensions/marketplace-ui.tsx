import { type ReactElement, type ReactNode } from 'react'
import { Plus, Search } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useTranslation } from 'react-i18next'
import type { MarketplaceKind } from '../../store/chat-store'
import type { Notice } from './marketplace-shared'
import { FeedbackNotice } from '../FeedbackNotice'

const KIND_ITEMS: Array<{
  value: MarketplaceKind
  labelKey: 'marketplaceKindMcp' | 'marketplaceKindSkills' | 'marketplaceKindPlugins'
}> = [
  { value: 'mcp', labelKey: 'marketplaceKindMcp' },
  { value: 'skills', labelKey: 'marketplaceKindSkills' },
  { value: 'plugins', labelKey: 'marketplaceKindPlugins' }
]

export function MarketplaceKindSwitch({
  value,
  onChange
}: {
  value: MarketplaceKind
  onChange: (next: MarketplaceKind) => void
}): ReactElement {
  const { t } = useTranslation('common')
  return (
    <div role="group" aria-label={t('extensions')} className="inline-flex shrink-0 items-center gap-1 rounded-xl bg-ds-subtle/60 p-1">
      {KIND_ITEMS.map((item) => (
        <button
          key={item.value}
          type="button"
          aria-pressed={item.value === value}
          onClick={() => onChange(item.value)}
          className={`rounded-lg px-4 py-2 text-[13px] font-medium transition-colors ${
            item.value === value
              ? 'bg-ds-card text-ds-ink shadow-sm'
              : 'text-ds-muted hover:bg-ds-hover hover:text-ds-ink'
          }`}
        >
          {t(item.labelKey)}
        </button>
      ))}
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
    <div className="flex items-end justify-between gap-3 border-b border-ds-border-muted px-1">
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
    <div className="flex min-w-0 flex-1 flex-wrap items-center justify-end gap-2">
      <label className="relative min-w-0 flex-1 sm:max-w-xs">
        <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-ds-faint" />
        <input
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          placeholder={placeholder}
          aria-label={placeholder}
          className="ds-ext-search h-10 w-full rounded-lg border border-ds-border bg-ds-card pl-11 pr-4 text-[13px] text-ds-ink outline-none transition focus:border-accent/40 focus:ring-1 focus:ring-accent/30"
        />
      </label>
      <div className="relative" ref={createHostRef}>
        <button
          type="button"
          onClick={onCreateToggle}
          aria-expanded={createOpen}
          className="inline-flex h-10 items-center justify-center gap-1.5 rounded-lg border border-ds-border bg-transparent px-3.5 text-[13px] font-medium leading-none text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink"
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

export function NoticeView({ notice, onDismiss }: { notice: Notice; onDismiss?: () => void }): ReactElement {
  return <div className="mt-4"><FeedbackNotice {...notice} onDismiss={onDismiss} /></div>
}
