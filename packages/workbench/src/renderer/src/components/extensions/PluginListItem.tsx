import { useEffect, useRef, useState } from 'react'
import { MessageCircle, MoreHorizontal, Power, Trash2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useLightDismiss } from '../../hooks/use-light-dismiss'
import { PluginIcon } from './PluginIcon'

export function PluginListItem({ pluginId, title, summary, onOpen, onUse, onRemove, removeLabel, busy = false }: {
  pluginId: string
  title: string
  summary: string
  onOpen: () => void
  onUse: () => void
  onRemove?: () => void
  removeLabel?: string
  busy?: boolean
}): React.JSX.Element {
  const { t } = useTranslation('common')
  const [open, setOpen] = useState(false)
  const menu = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const close = (): void => { setOpen(false); trigger.current?.focus() }
  useLightDismiss({ open, onDismiss: close, refs: [menu, trigger] })
  useEffect(() => { if (open) menu.current?.querySelector<HTMLButtonElement>('button:not(:disabled)')?.focus() }, [open])
  const desktop = pluginId === 'computer-use'
  const ActionIcon = desktop ? Power : Trash2
  return <li className="relative flex min-w-0 items-center rounded-xl pr-2 transition-colors hover:bg-ds-subtle/50">
    <button type="button" onClick={onOpen}
      className="group flex min-h-24 min-w-0 flex-1 items-center gap-4 rounded-xl px-3 py-5 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent">
      <PluginIcon pluginId={pluginId} />
      <span className="min-w-0 flex-1">
        <span className="block text-[16px] font-medium leading-6 text-ds-ink">{title}</span>
        <span className="mt-1 block text-[14px] leading-6 text-ds-muted">{summary}</span>
      </span>
    </button>
    <div className="relative shrink-0">
      <button ref={trigger} type="button" aria-label={`${title} · ${t('pluginManage')}`} aria-haspopup="menu" aria-expanded={open}
        onClick={() => setOpen(!open)} className="rounded-lg p-2 text-ds-muted hover:bg-ds-hover"><MoreHorizontal className="size-5" /></button>
      {open ? <div ref={menu} role="menu" aria-label={title} className="ds-popover-surface absolute left-0 top-full mt-1 z-20 w-44 rounded-xl border border-ds-border p-1.5 shadow-lg"
        onKeyDown={event => {
          if (!['ArrowDown', 'ArrowUp', 'Home', 'End', 'Tab'].includes(event.key)) return
          if (event.key === 'Tab') { setOpen(false); return }
          event.preventDefault()
          const buttons = Array.from(menu.current!.querySelectorAll<HTMLButtonElement>('button:not(:disabled)'))
          const current = buttons.indexOf(document.activeElement as HTMLButtonElement)
          const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : (current + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length
          buttons[next]?.focus()
        }}>
        <button role="menuitem" type="button" disabled={busy} onClick={() => { setOpen(false); onUse() }} className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-ds-ink hover:bg-ds-hover disabled:opacity-40"><MessageCircle className="size-4" />{t('pluginUseNow')}</button>
        {onRemove ? <>
          <div role="separator" className="my-1 border-t border-ds-border" />
          <button role="menuitem" type="button" disabled={busy} onClick={() => { close(); onRemove() }} className={`flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm hover:bg-ds-hover disabled:opacity-40 ${desktop ? 'text-ds-ink' : 'text-ds-danger'}`}><ActionIcon className="size-4" />{removeLabel ?? t('pluginUninstall')}</button>
        </> : null}
      </div> : null}
    </div>
  </li>
}
