import type { ReactElement } from 'react'

export function SettingsToggle({
  checked,
  onChange,
  disabled = false,
  label
}: {
  checked: boolean
  disabled?: boolean
  label?: string
  onChange: (v: boolean) => void
}): ReactElement {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative h-7 w-12 shrink-0 rounded-full transition disabled:cursor-not-allowed disabled:opacity-40 ${
        checked ? 'bg-accent' : 'bg-ds-faint'
      }`}
    >
      <span
        className={`absolute top-0.5 h-6 w-6 rounded-full bg-white shadow transition ${
          checked ? 'left-6' : 'left-0.5'
        }`}
      />
    </button>
  )
}
