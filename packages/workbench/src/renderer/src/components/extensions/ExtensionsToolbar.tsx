import { useRef, useState, type ReactElement, type ReactNode } from 'react'
import { MoreHorizontal } from 'lucide-react'
import { useLightDismiss } from '../../hooks/use-light-dismiss'

export type ExtensionsMenuItem = {
  label: string
  icon?: ReactElement
  onClick: () => void
  disabled?: boolean
}

type Props = {
  /** Primary action (accent button, optionally wrapped for popover anchoring). */
  children: ReactNode
  menuItems?: ExtensionsMenuItem[]
}

/** One secondary action becomes a labeled button; two or more stay under "…". */
export function ExtensionsToolbar({ children, menuItems = [] }: Props): ReactElement {
  const [open, setOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  useLightDismiss({
    open,
    onDismiss: () => setOpen(false),
    refs: [menuRef]
  })

  const sole = menuItems.length === 1 ? menuItems[0] : null
  const overflow = menuItems.length > 1

  return (
    <div className="flex items-center gap-2">
      {sole ? (
        <button
          type="button"
          disabled={sole.disabled}
          onClick={sole.onClick}
          className="ds-ext-toolbar-menu inline-flex items-center justify-center gap-2 rounded-xl border border-ds-border bg-ds-subtle px-3 py-2 text-[13px] font-semibold leading-none text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink disabled:opacity-50"
        >
          {sole.icon ? <span className="shrink-0">{sole.icon}</span> : null}
          {sole.label}
        </button>
      ) : null}
      {overflow ? (
        <div className="relative" ref={menuRef}>
          <button
            type="button"
            onClick={() => setOpen((value) => !value)}
            className="ds-ext-toolbar-menu inline-flex h-9 w-9 items-center justify-center rounded-xl border border-ds-border bg-ds-subtle text-ds-muted transition hover:bg-ds-hover hover:text-ds-ink"
            aria-label="More actions"
            aria-expanded={open}
          >
            <MoreHorizontal className="h-4 w-4" strokeWidth={1.85} />
          </button>
          {open ? (
            <div className="ds-popover-surface absolute right-0 top-full z-20 mt-1.5 min-w-[10.5rem] overflow-hidden rounded-xl py-1 shadow-lg">
              {menuItems.map((item) => (
                <button
                  key={item.label}
                  type="button"
                  disabled={item.disabled}
                  onClick={() => {
                    setOpen(false)
                    item.onClick()
                  }}
                  className="ds-ext-menu-item flex w-full items-center gap-2 px-3.5 py-2 text-left text-[13px] text-ds-ink transition hover:bg-ds-subtle/60 disabled:opacity-50"
                >
                  {item.icon ? <span className="shrink-0 text-ds-muted">{item.icon}</span> : null}
                  {item.label}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
      {children}
    </div>
  )
}
