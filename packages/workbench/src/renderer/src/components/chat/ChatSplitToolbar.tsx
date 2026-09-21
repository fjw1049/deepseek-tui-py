import { useEffect, useId, useLayoutEffect, useRef, useState, type CSSProperties } from 'react'
import { createPortal } from 'react-dom'
import { Check, ChevronDown, Columns2, LayoutGrid, Plus, Rows2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useLightDismiss } from '../../hooks/use-light-dismiss'
import { MAX_CHAT_PANES, type ChatArrangement, type ChatLayout } from '../../store/chat-layout-store'

export function ChatSplitToolbar({ layout, onArrange, onAdd }: {
  layout: ChatLayout; onArrange: (arrangement: ChatArrangement) => void; onAdd: () => void
}) {
  const { t } = useTranslation('common')
  const [open, setOpen] = useState(false)
  const [style, setStyle] = useState<CSSProperties>({})
  const trigger = useRef<HTMLButtonElement>(null)
  const panel = useRef<HTMLDivElement>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const focusOnOpen = useRef(false)
  const panelId = useId()
  const cancelClose = (): void => { if (timer.current) clearTimeout(timer.current) }
  const close = (): void => { cancelClose(); setOpen(false) }
  const leave = (): void => {
    cancelClose()
    timer.current = setTimeout(() => {
      if (!panel.current?.contains(document.activeElement)) setOpen(false)
    }, 180)
  }
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current) }, [])
  useLightDismiss({ open, refs: [trigger, panel], onDismiss: () => {
    if (panel.current?.contains(document.activeElement)) trigger.current?.focus()
    close()
  } })
  useLayoutEffect(() => {
    if (!open) return
    const update = (): void => {
      const rect = trigger.current!.getBoundingClientRect()
      const scale = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--ds-ui-scale')) || 1
      setStyle({ position: 'fixed', zIndex: 120, top: rect.bottom / scale + 6,
        left: Math.max(8, Math.min(rect.left / scale, window.innerWidth / scale - 208)) })
    }
    update()
    if (focusOnOpen.current) {
      panel.current?.querySelector<HTMLButtonElement>('[aria-pressed="true"]')?.focus()
      focusOnOpen.current = false
    }
    window.addEventListener('resize', update)
    return () => window.removeEventListener('resize', update)
  }, [open])
  return <div className="ds-chat-split-toolbar ds-no-drag">
    <button ref={trigger} type="button" className="ds-chat-split-task-trigger ds-chat-split-arrangement-trigger" aria-expanded={open}
      aria-haspopup="dialog" aria-controls={open ? panelId : undefined}
      onMouseEnter={() => { cancelClose(); setOpen(true) }} onMouseLeave={leave}
      onClick={() => {
        cancelClose()
        focusOnOpen.current = !open
        setOpen(true)
        panel.current?.querySelector<HTMLButtonElement>('[aria-pressed="true"]')?.focus()
      }}>
      <span>{t('splitArrangement')}</span><ChevronDown size={12} aria-hidden="true" />
    </button>
    {open && createPortal(<div ref={panel} id={panelId} style={style} role="dialog" aria-label={t('splitArrangement')}
      className="ds-project-context-menu ds-chat-split-arrangements ds-no-drag"
      onMouseEnter={cancelClose} onMouseLeave={leave}
      onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget) && event.relatedTarget !== trigger.current) close() }}>
      {([['grid', LayoutGrid, 'splitGrid'], ['horizontal', Columns2, 'splitHorizontal'], ['vertical', Rows2, 'splitVertical']] as const).map(([value, Icon, label]) => {
        const selected = (layout.arrangement ?? 'grid') === value
        return <button key={value} type="button"
          className={`ds-project-context-menu__row ${selected ? 'ds-project-context-menu__row--active' : ''}`}
          aria-pressed={selected} onClick={() => { onArrange(value); close(); trigger.current?.focus() }}>
          <Icon size={16} strokeWidth={1.75} aria-hidden="true" /><span className="flex-1">{t(label)}</span>
          {selected ? <Check size={14} aria-hidden="true" /> : null}
        </button>
      })}
    </div>, document.body)}
    <button type="button" className="ds-chat-split-icon" aria-label={t('splitAddPane')}
      title={t(layout.panes.length >= MAX_CHAT_PANES ? 'splitLimit' : 'splitAddPane')}
      disabled={layout.panes.length >= MAX_CHAT_PANES} onClick={onAdd}><Plus size={16} strokeWidth={1.75} aria-hidden="true" /></button>
  </div>
}
