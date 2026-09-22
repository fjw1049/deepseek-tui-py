import { useEffect, useId, useLayoutEffect, useRef, useState, type CSSProperties } from 'react'
import { createPortal } from 'react-dom'
import { ChevronDown, Plus, ScrollText, Search } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useComboboxNav } from '../../hooks/use-combobox-nav'
import { useLightDismiss } from '../../hooks/use-light-dismiss'
import { workspaceLabelFromPath } from '../../lib/workspace-label'
import { useChatStore } from '../../store/chat-store'

export function ChatSplitTaskPicker({ visibleThreadIds, workspace, onSelect, onCreate }: {
  visibleThreadIds: (string | null)[]; workspace: string; onSelect: (id: string) => void; onCreate: () => Promise<void>
}) {
  const { t } = useTranslation('common')
  const threads = useChatStore(s => s.threads)
  const ready = useChatStore(s => s.runtimeConnection === 'ready')
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState('')
  const [style, setStyle] = useState<CSSProperties>({})
  const trigger = useRef<HTMLButtonElement>(null)
  const panel = useRef<HTMLDivElement>(null)
  const listId = useId()
  const options = threads.filter(th => !th.archived && th.workspace && `${th.title} ${th.workspace}`.toLowerCase().includes(query.trim().toLowerCase()))
  const nav = useComboboxNav(options.length, open)
  const close = (): void => { setOpen(false); trigger.current?.focus() }
  useLightDismiss({ open, refs: [trigger, panel], onDismiss: () => setOpen(false) })
  useEffect(() => { if (!open) setQuery('') }, [open])
  useEffect(() => {
    if (open) panel.current?.querySelector(`[data-combobox-index="${nav.highlighted}"]`)?.scrollIntoView({ block: 'nearest' })
  }, [open, nav.highlighted])
  useLayoutEffect(() => {
    if (!open) return
    const update = (): void => {
      const rect = trigger.current!.getBoundingClientRect()
      const scale = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--ds-ui-scale')) || 1
      const width = Math.min(340, window.innerWidth / scale - 24)
      const below = window.innerHeight / scale - rect.bottom / scale - 20
      const above = rect.top / scale - 20
      const placeBelow = below >= 240 || below >= above
      setStyle({ position: 'fixed', zIndex: 120, width,
        left: Math.max(12, Math.min(rect.left / scale, window.innerWidth / scale - width - 12)),
        ...(placeBelow ? { top: rect.bottom / scale + 8 } : { bottom: window.innerHeight / scale - rect.top / scale + 8 }),
        maxHeight: Math.max(80, placeBelow ? below : above) })
    }
    update()
    const observer = new ResizeObserver(update)
    observer.observe(trigger.current!)
    window.addEventListener('resize', update)
    return () => { observer.disconnect(); window.removeEventListener('resize', update) }
  }, [open])
  const choose = (id: string): void => { close(); onSelect(id) }
  return <>
    <button ref={trigger} type="button" className="ds-chat-split-task-trigger" aria-expanded={open} aria-haspopup="dialog"
      onClick={() => setOpen(value => !value)}>
      <ScrollText size={16} strokeWidth={1.75} className="shrink-0 text-ds-faint" aria-hidden="true" />
      <span className="truncate">{t('splitChooseTask')}</span><ChevronDown size={12} className="shrink-0 text-ds-faint" aria-hidden="true" />
    </button>
    {open && createPortal(<div ref={panel} style={style} role="dialog" aria-label={t('splitChooseTask')}
      className="ds-project-context-menu ds-no-drag flex flex-col overflow-hidden"
      onKeyDown={event => { if (event.key === 'Escape') { event.stopPropagation(); close() } }}>
      <div className="ds-project-context-menu__header shrink-0">
        <label className="ds-project-context-menu__search">
          <Search size={14} aria-hidden="true" />
          <input autoFocus role="combobox" aria-label={t('splitSearchTasks')} aria-expanded={open} aria-controls={listId}
            aria-autocomplete="list" aria-activedescendant={options[nav.highlighted] ? `${listId}-${nav.highlighted}` : undefined}
            className="ds-project-context-menu__search-input" placeholder={t('splitSearchTasks')} value={query}
            onChange={event => setQuery(event.target.value)}
            onKeyDown={event => nav.onKeyDown(event, index => choose(options[index].id))} />
        </label>
      </div>
      <div id={listId} role="listbox" aria-label={t('splitChooseTask')} className="ds-project-context-menu__list min-h-0">
        {!options.length ? <div className="ds-project-context-menu__empty">{t('splitNoTasks')}</div> : options.map((thread, index) =>
          <button key={thread.id} id={`${listId}-${index}`} type="button" role="option" aria-selected={nav.highlighted === index}
            data-combobox-index={index} onMouseEnter={() => nav.setHighlighted(index)} onClick={() => choose(thread.id)}
            className={`ds-project-context-menu__row ${nav.highlighted === index ? 'ds-project-context-menu__row--highlight' : ''}`}>
            <ScrollText size={15} className="shrink-0 text-ds-faint" aria-hidden="true" />
            <span className="min-w-0 flex-1"><span className="ds-project-context-menu__row-title truncate" title={thread.title}>{thread.title}</span>
              <span className="ds-project-context-menu__row-path" title={thread.workspace}>{workspaceLabelFromPath(thread.workspace!)}</span></span>
            {visibleThreadIds.includes(thread.id) ? <span className="shrink-0 text-[11px] text-ds-faint">{t('splitAlreadyOpen')}</span> : null}
          </button>)}
      </div>
      <div className="ds-project-context-menu__footer shrink-0">
        {error ? <p role="alert" className="px-2 py-1 text-xs text-red-500">{error}</p> : null}
        <button type="button" disabled={!ready || creating} className="ds-project-context-menu__row" onClick={async () => {
          setCreating(true); setError('')
          try { await onCreate(); close() } catch { setError(t('splitCreateFailed')) } finally { setCreating(false) }
        }}>
          <Plus size={15} className="shrink-0 text-ds-faint" aria-hidden="true" />
          <span className="min-w-0 flex-1"><span className="ds-project-context-menu__row-title">{t('splitNewTask')}</span>
            <span className="ds-project-context-menu__row-path" title={workspace}>{workspaceLabelFromPath(workspace)}</span></span>
        </button>
      </div>
    </div>, document.body)}
  </>
}
