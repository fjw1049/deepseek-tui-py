import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import './composer-plus-menu.css'
import { Check, Loader2, Search } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useComboboxNav } from '../../hooks/use-combobox-nav'

export type ComposerPlusGroup = {
  id: string
  label: string
  loading?: boolean
  empty?: string
  items: Array<{
    id: string
    label: string
    description?: string
    keywords?: string
    icon: ReactNode
    disabled?: boolean
    selected?: boolean
    onSelect: () => void
  }>
}

export function ComposerPlusMenu({ groups, onClose }: {
  groups: ComposerPlusGroup[]
  onClose: () => void
}) {
  const { t } = useTranslation('common')
  const [query, setQuery] = useState('')
  const searchRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const id = useId()
  const needle = query.trim().toLowerCase()
  const visible = groups.map(group => ({ ...group, items: group.items.filter(item =>
    `${group.label} ${item.label} ${item.description ?? ''} ${item.keywords ?? ''}`.toLowerCase().includes(needle)
  ) }))
  const selectable = visible.flatMap(group => group.items).filter(item => !item.disabled)
  const nav = useComboboxNav(selectable.length, true)
  const active = selectable[nav.highlighted]
  useEffect(() => { searchRef.current?.focus() }, [])
  useEffect(() => {
    listRef.current?.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: 'nearest' })
  }, [active?.id])
  const choose = (item: ComposerPlusGroup['items'][number]) => {
    if (item.disabled) return
    onClose()
    item.onSelect()
  }
  return (
    <div
      role="dialog"
      aria-label={t('composerPlusMenu')}
      className="ds-composer-plus-menu ds-morph-pop absolute inset-x-0 bottom-full z-40 mb-2 flex max-h-[min(400px,50vh)] flex-col overflow-hidden rounded-[20px] border border-ds-border bg-ds-card shadow-[0_8px_28px_rgba(0,0,0,0.10)]"
      onKeyDown={event => {
        if (event.key === 'Escape') {
          event.preventDefault()
          event.stopPropagation()
          onClose()
        }
      }}
    >
      <div className="flex shrink-0 items-center gap-3 border-b border-ds-border-muted px-4 py-2.5">
        <Search className="h-[18px] w-[18px] shrink-0 text-ds-faint" strokeWidth={1.7} />
        <input
          ref={searchRef}
          role="combobox"
          aria-expanded
          aria-controls={`${id}-list`}
          aria-activedescendant={active ? `${id}-${active.id}` : undefined}
          aria-autocomplete="list"
          aria-label={t('composerPlusSearch')}
          placeholder={t('composerPlusSearch')}
          value={query}
          onChange={event => { setQuery(event.target.value); nav.setHighlighted(0) }}
          onKeyDown={event => {
            if (event.nativeEvent.isComposing) return
            nav.onKeyDown(event, index => { if (selectable[index]) choose(selectable[index]) })
          }}
          className="ds-composer-plus-menu__search min-w-0 flex-1 bg-transparent text-[14px] text-ds-ink outline-none placeholder:text-ds-faint"
        />
      </div>
      <div ref={listRef} id={`${id}-list`} role="listbox" aria-label={t('composerPlusMenu')} className="ds-scroll-surface min-h-0 overflow-y-auto p-1.5">
        {visible.map(group => (!needle || group.items.length > 0) && (
          <div key={group.id} role="group" aria-labelledby={`${id}-${group.id}-heading`} className="mb-0.5">
            <div id={`${id}-${group.id}-heading`} className="ds-composer-plus-menu__heading flex items-center gap-2 px-3 pb-1 pt-1.5">
              {group.label}
              {group.loading && <Loader2 className="h-3 w-3 animate-spin" aria-label={t('loading')} />}
            </div>
            {group.items.map(item => (
              <button
                key={item.id}
                id={`${id}-${item.id}`}
                role="option"
                aria-selected={active?.id === item.id}
                aria-disabled={item.disabled || undefined}
                type="button"
                tabIndex={-1}
                title={[item.label, item.description].filter(Boolean).join(' — ')}
                onMouseDown={event => event.preventDefault()}
                onMouseEnter={() => { if (!item.disabled) nav.setHighlighted(selectable.indexOf(item)) }}
                onClick={() => choose(item)}
                className={`ds-composer-plus-menu__row flex h-7 w-full items-center gap-2.5 rounded-xl px-3 py-1 text-left text-[13px] transition-colors ${item.disabled ? 'text-ds-faint opacity-50' : active?.id === item.id ? 'bg-ds-hover text-ds-ink' : 'text-ds-muted hover:bg-ds-hover'}`}
              >
                <span className="flex h-5 w-5 shrink-0 items-center justify-center">{item.icon}</span>
                <span className="ds-composer-plus-menu__label ds-sidebar-title-fade max-w-[65%] shrink-0 overflow-hidden whitespace-nowrap pr-6 -mr-6 font-medium">{item.label}</span>
                <span className="ds-composer-plus-menu__description ds-sidebar-title-fade ml-1 min-w-0 flex-1 overflow-hidden whitespace-nowrap text-[12px]">{item.description}</span>
                {item.selected && <Check className="h-4 w-4 shrink-0 text-ds-muted" aria-label={t('slashCommandCurrent')} />}
              </button>
            ))}
            {!group.loading && group.items.length === 0 && group.empty && <p className="px-3 py-2 text-[12px] text-ds-faint">{group.empty}</p>}
          </div>
        ))}
        {needle && visible.every(group => group.items.length === 0) && <p role="status" className="px-3 py-5 text-center text-[13px] text-ds-faint">{t('composerPlusNoResults')}</p>}
      </div>
    </div>
  )
}
