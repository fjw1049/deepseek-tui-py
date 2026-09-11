import { useEffect, useId, useRef, useState, type ReactElement } from 'react'
import { Check, CircleCheck, ChevronDown, GitFork, ListTodo } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { RunTarget } from '../../store/run-panel-store'
import { useLightDismiss } from '../../hooks/use-light-dismiss'
import { isRunActive, runStatusKey } from '../../lib/run-activity'
import { RunStateIcon } from './RunActivity'

export type RunOption = Omit<RunTarget, 'threadId'> & { label: string; status?: string }

export function RunSwitcher({ current, options, onSelect }: {
  current: RunOption | null
  options: RunOption[]
  onSelect: (option: RunOption) => void
}): ReactElement {
  const { t } = useTranslation('common')
  const [open, setOpen] = useState(false)
  const hoverOpened = useRef(false)
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const cancelClose = (): void => { if (closeTimer.current) clearTimeout(closeTimer.current) }
  useEffect(() => () => cancelClose(), [])
  const rootRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const menuId = useId()
  const Icon = current?.kind === 'task' ? ListTodo : GitFork
  const close = (): void => setOpen(false)
  useLightDismiss({ open, onDismiss: close, refs: [rootRef] })
  useEffect(() => {
    if (open && !hoverOpened.current) {
      const selected = menuRef.current?.querySelector<HTMLButtonElement>('[aria-checked="true"]')
      const first = menuRef.current?.querySelector<HTMLButtonElement>('[role="menuitemradio"]')
      ;(selected ?? first)?.focus()
    }
  }, [open])
  return (
    <div className="ds-run-switcher" ref={rootRef} onPointerEnter={(event) => {
      if (event.pointerType !== 'mouse') return
      cancelClose()
      if (!open) { hoverOpened.current = true; setOpen(true) }
    }} onPointerLeave={() => {
      if (hoverOpened.current) closeTimer.current = setTimeout(() => {
        if (!rootRef.current?.contains(document.activeElement)) close()
      }, 200)
    }}>
      <button
        type="button"
        ref={triggerRef}
        className="ds-run-title-button"
        aria-label={t('runPanelSelect')}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => {
          if (hoverOpened.current) {
            hoverOpened.current = false
            menuRef.current?.querySelector<HTMLButtonElement>('[aria-checked="true"]')?.focus()
          } else setOpen((value) => !value)
        }}
      >
        <span className="ds-run-agent-mark"><Icon aria-hidden /></span>
        <span className="ds-run-title">{current?.label || t('runPanelSelect')}</span>
        <ChevronDown className="ds-run-switch-chevron" aria-hidden />
      </button>
      {open ? (
        <div id={menuId} className="ds-run-menu" role="menu" aria-label={t('runPanelSelect')} ref={menuRef} onKeyDown={(event) => {
          if (event.key === 'Escape') {
            event.preventDefault()
            event.stopPropagation()
            close()
            triggerRef.current?.focus()
            return
          }
          if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return
          event.preventDefault()
          const buttons = [...event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]')]
          const index = buttons.indexOf(document.activeElement as HTMLButtonElement)
          const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1
            : (index + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length
          buttons[next]?.focus()
        }}>
          {[true, false].map((active) => {
            const group = options.filter((option) => isRunActive(option.status) === active)
            if (!group.length) return null
            return (
              <div key={String(active)} role="group" aria-label={t(active ? 'runPanelActiveGroup' : 'runPanelDoneGroup')}>
                {group.map((option) => {
                  const selected = option.kind === current?.kind && option.id === current.id
                  return (
                    <button key={`${option.kind}:${option.id}`} type="button" role="menuitemradio" aria-checked={selected} className="ds-run-menu-item" onClick={() => {
                      onSelect(option)
                      close()
                      triggerRef.current?.focus()
                    }}>
                      <span className="ds-run-menu-status" role="img" aria-label={t(runStatusKey(option.status))} title={t(runStatusKey(option.status))}>
                        {option.status === 'completed' || option.status === 'ok'
                          ? <CircleCheck className="ds-run-state-icon ds-run-menu-completed" aria-hidden />
                          : <RunStateIcon status={option.status} />}
                      </span>
                      <span className="ds-run-menu-item-text"><span>{option.label}</span></span>
                      {selected ? <Check className="ds-run-menu-check" aria-hidden /> : null}
                    </button>
                  )
                })}
              </div>
            )
          })}
        </div>
      ) : null}
    </div>
  )
}
