import {
  Children,
  isValidElement,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type CSSProperties,
  type ReactElement,
  type ReactNode,
  type SelectHTMLAttributes
} from 'react'
import { createPortal } from 'react-dom'
import { Check, ChevronDown } from 'lucide-react'
import { useComboboxNav } from '../../hooks/use-combobox-nav'
import { useLightDismiss } from '../../hooks/use-light-dismiss'

type OptionItem = {
  value: string
  label: string
  disabled: boolean
}

function collectOptions(children: ReactNode): OptionItem[] {
  const items: OptionItem[] = []
  Children.forEach(children, (child) => {
    if (!isValidElement(child) || child.type !== 'option') return
    const props = child.props as {
      value?: string | number
      children?: ReactNode
      disabled?: boolean
    }
    const value =
      props.value != null ? String(props.value) : String(props.children ?? '').trim()
    const content = props.children
    const label =
      typeof content === 'string' || typeof content === 'number' ? String(content) : value
    items.push({ value, label, disabled: Boolean(props.disabled) })
  })
  return items
}

function emitChange(
  onChange: SelectHTMLAttributes<HTMLSelectElement>['onChange'],
  next: string,
  name?: string
): void {
  if (!onChange) return
  onChange({
    target: { value: next, name: name ?? '' },
    currentTarget: { value: next, name: name ?? '' }
  } as ChangeEvent<HTMLSelectElement>)
}

/** body uses `zoom: var(--ds-ui-scale)` — layout px ≠ getBoundingClientRect px. */
function readUiScale(): number {
  const n = parseFloat(
    getComputedStyle(document.documentElement).getPropertyValue('--ds-ui-scale')
  )
  return Number.isFinite(n) && n > 0 ? n : 1
}

function wrapperClass(disabled: boolean | undefined, extra: string): string {
  const hasWidth = /(^|\s)w-/.test(extra)
  const hasHeight = /(^|\s)h-/.test(extra)
  const hasRadius = /(^|\s)rounded-/.test(extra)
  return [
    'relative min-w-0 border border-ds-border bg-ds-card shadow-sm',
    hasHeight ? '' : 'h-8',
    hasWidth ? '' : 'w-full',
    hasRadius ? '' : 'rounded-lg',
    'transition focus-within:border-accent/40 focus-within:ring-1 focus-within:ring-accent/30',
    disabled ? 'cursor-not-allowed opacity-55' : '',
    extra
  ]
    .filter(Boolean)
    .join(' ')
}

export function SettingsSelect({
  className = '',
  wrapperClassName = '',
  selectClassName = '',
  children,
  value,
  disabled,
  onChange,
  name,
  id,
  title,
  'aria-label': ariaLabel
}: SelectHTMLAttributes<HTMLSelectElement> & {
  wrapperClassName?: string
  /** Extra classes on the outer shell (e.g. bg-ds-main). */
  selectClassName?: string
}): ReactElement {
  const options = useMemo(() => collectOptions(children), [children])
  const selectedValue = value == null || value === '' ? '' : String(value)
  const label =
    options.find((item) => item.value === selectedValue)?.label ?? selectedValue

  const [open, setOpen] = useState(false)
  const [menuStyle, setMenuStyle] = useState<CSSProperties | null>(null)
  const [placement, setPlacement] = useState<'above' | 'below'>('below')
  const wrapRef = useRef<HTMLDivElement | null>(null)
  const triggerRef = useRef<HTMLButtonElement | null>(null)
  const menuRef = useRef<HTMLDivElement | null>(null)
  const optionsRef = useRef(options)
  const selectedRef = useRef(selectedValue)
  optionsRef.current = options
  selectedRef.current = selectedValue
  const { highlighted, setHighlighted, onKeyDown } = useComboboxNav(options.length, open)

  const updateMenuPosition = useCallback((): void => {
    const trigger = wrapRef.current ?? triggerRef.current
    if (!trigger) return
    const scale = readUiScale()
    const rect = trigger.getBoundingClientRect()
    const gap = 6
    const gutter = 12
    // getBoundingClientRect / innerWidth are post-zoom. fixed left/top/width
    // on a body-portaled node are pre-zoom — same rule as ThreadHoverCard.
    const left = rect.left / scale
    const width = rect.width / scale
    const top = rect.bottom / scale
    const viewH = window.innerHeight / scale
    const spaceBelow = viewH - top - gutter
    const nextPlacement = spaceBelow < 96 ? 'above' : 'below'
    const maxHeight =
      nextPlacement === 'below'
        ? Math.max(96, spaceBelow - gap)
        : Math.max(96, rect.top / scale - gutter - gap)
    setPlacement(nextPlacement)
    setMenuStyle({
      position: 'fixed',
      left,
      width,
      zIndex: 120,
      maxHeight,
      ...(nextPlacement === 'below'
        ? { top: top + gap }
        : { bottom: viewH - rect.top / scale + gap })
    })
  }, [])

  useLayoutEffect(() => {
    if (!open) {
      setMenuStyle(null)
      return
    }
    updateMenuPosition()
    window.addEventListener('resize', updateMenuPosition)
    window.addEventListener('scroll', updateMenuPosition, true)
    return () => {
      window.removeEventListener('resize', updateMenuPosition)
      window.removeEventListener('scroll', updateMenuPosition, true)
    }
  }, [open, updateMenuPosition])

  useEffect(() => {
    if (!open) return
    const index = optionsRef.current.findIndex((item) => item.value === selectedRef.current)
    setHighlighted(index >= 0 ? index : 0)
  }, [open, setHighlighted])

  useEffect(() => {
    if (!open) return
    menuRef.current
      ?.querySelector('[data-settings-select-highlight="true"]')
      ?.scrollIntoView({ block: 'nearest' })
  }, [highlighted, open])

  useLightDismiss({
    open,
    onDismiss: () => setOpen(false),
    refs: [wrapRef, menuRef],
    enabled: !disabled
  })

  const commit = useCallback(
    (next: string): void => {
      setOpen(false)
      if (next === selectedValue) return
      emitChange(onChange, next, name)
    },
    [name, onChange, selectedValue]
  )

  useEffect(() => {
    if (!open || disabled) return
    const onKey = (event: KeyboardEvent): void => {
      onKeyDown(event, (index) => {
        const option = options[index]
        if (!option || option.disabled) return
        commit(option.value)
      })
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [commit, disabled, onKeyDown, open, options])

  const menu =
    open && menuStyle && typeof document !== 'undefined'
      ? createPortal(
          <div
            ref={menuRef}
            style={menuStyle}
            role="listbox"
            aria-label={ariaLabel || title}
            className={`ds-project-context-menu ds-morph-pop ds-settings-select-menu ds-morph-stagger overflow-y-auto p-1 ${
              placement === 'below' ? 'ds-settings-select-menu--below' : ''
            }`}
            onMouseDown={(event) => event.stopPropagation()}
          >
              {options.map((option, index) => {
                const selected = option.value === selectedValue
                const active = index === highlighted
                return (
                  <button
                    key={`${option.value}:${index}`}
                    type="button"
                    role="option"
                    aria-selected={selected}
                    disabled={option.disabled}
                    data-settings-select-highlight={active ? 'true' : undefined}
                    className={`ds-project-context-menu__row ${
                      selected ? 'ds-project-context-menu__row--active' : ''
                    } ${active ? 'ds-project-context-menu__row--highlight' : ''}`}
                    onMouseEnter={() => setHighlighted(index)}
                    onClick={() => {
                      if (option.disabled) return
                      commit(option.value)
                    }}
                  >
                    <span className="ds-project-context-menu__row-title min-w-0 flex-1">
                      {option.label}
                    </span>
                    {selected ? (
                      <Check className="h-4 w-4 shrink-0 text-accent" strokeWidth={2.2} />
                    ) : (
                      <span className="h-4 w-4 shrink-0" aria-hidden />
                    )}
                  </button>
                )
              })}
          </div>,
          document.body
        )
      : null

  return (
    <div
      ref={wrapRef}
      className={wrapperClass(disabled, `${selectClassName} ${wrapperClassName} ${className}`.trim())}
    >
      <button
        ref={triggerRef}
        id={id}
        type="button"
        disabled={disabled}
        title={title}
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="relative flex h-full w-full cursor-pointer items-center justify-center px-2.5 pr-7 text-center disabled:cursor-not-allowed"
        onClick={() => {
          if (disabled) return
          setOpen((current) => !current)
        }}
        onKeyDown={(event) => {
          if (disabled || open) return
          if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault()
            setOpen(true)
          }
        }}
      >
        <span className="w-full truncate text-[13px] font-medium leading-none text-ds-ink">
          {label}
        </span>
        <ChevronDown
          className={`pointer-events-none absolute right-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ds-faint transition-transform duration-200 ${
            open ? 'rotate-180' : ''
          }`}
          strokeWidth={1.75}
          aria-hidden
        />
      </button>
      {menu}
    </div>
  )
}
