import {
  Children,
  isValidElement,
  useMemo,
  type ReactElement,
  type ReactNode,
  type SelectHTMLAttributes
} from 'react'
import { ChevronDown } from 'lucide-react'

function findOptionLabel(
  children: ReactNode,
  value: string | number | readonly string[] | undefined
): string {
  if (value == null || value === '') return ''
  const target = Array.isArray(value) ? String(value[0] ?? '') : String(value)

  let label = ''
  Children.forEach(children, (child) => {
    if (label || !isValidElement(child) || child.type !== 'option') return
    const props = child.props as { value?: string | number; children?: ReactNode }
    const optionValue =
      props.value != null ? String(props.value) : String(props.children ?? '').trim()
    if (optionValue !== target) return
    const content = props.children
    label =
      typeof content === 'string' || typeof content === 'number'
        ? String(content)
        : optionValue
  })
  return label
}

function wrapperClass(disabled: boolean | undefined, extra: string): string {
  return [
    'relative h-10 w-full min-w-0 rounded-xl border border-ds-border bg-ds-card shadow-sm',
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
  ...props
}: SelectHTMLAttributes<HTMLSelectElement> & {
  wrapperClassName?: string
  /** Extra classes on the outer shell (e.g. bg-ds-main). */
  selectClassName?: string
}): ReactElement {
  const label = useMemo(() => findOptionLabel(children, value), [children, value])

  return (
    <div className={wrapperClass(disabled, `${selectClassName} ${wrapperClassName} ${className}`.trim())}>
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 flex items-center justify-center px-3 pr-9"
      >
        <span className="w-full truncate text-center text-[14px] font-medium leading-none text-ds-ink">
          {label}
        </span>
      </div>
      <select
        {...props}
        value={value}
        disabled={disabled}
        className="absolute inset-0 z-[1] h-full w-full cursor-pointer opacity-0 disabled:cursor-not-allowed"
      >
        {children}
      </select>
      <ChevronDown
        className="pointer-events-none absolute right-3 top-1/2 z-[2] h-4 w-4 -translate-y-1/2 text-ds-faint"
        strokeWidth={1.75}
        aria-hidden
      />
    </div>
  )
}
