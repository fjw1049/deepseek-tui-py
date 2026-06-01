import type { ReactElement, ReactNode } from 'react'

export function SettingsActionToolbar({
  children,
  className = ''
}: {
  children: ReactNode
  className?: string
}): ReactElement {
  return <div className={`flex flex-wrap gap-2 ${className}`.trim()}>{children}</div>
}

export function settingsToolbarButtonClass(disabled = false): string {
  return `inline-flex items-center gap-1.5 rounded-xl border border-ds-border bg-ds-card px-3 py-2 text-[13px] font-medium text-ds-ink shadow-sm transition hover:bg-ds-hover ${
    disabled ? 'cursor-not-allowed opacity-55' : ''
  }`
}
