import type { ReactElement, ReactNode } from 'react'

export function SettingsActionToolbar({
  children,
  className = ''
}: {
  children: ReactNode
  className?: string
}): ReactElement {
  return (
    <div className={`flex flex-wrap items-center justify-center gap-2 ${className}`.trim()}>
      {children}
    </div>
  )
}

export function settingsToolbarButtonClass(disabled = false): string {
  return `inline-flex items-center justify-center gap-1.5 rounded-xl border border-ds-border bg-ds-card px-3 py-2 text-center text-[13px] font-medium leading-none text-ds-ink shadow-sm transition hover:bg-ds-hover ${
    disabled ? 'cursor-not-allowed opacity-55' : ''
  }`
}

/** Full-width settings row actions (workspace picker, etc.). */
export function settingsBlockButtonClass(disabled = false): string {
  return `inline-flex w-full items-center justify-center rounded-xl border border-ds-border bg-ds-card px-3 py-2 text-center text-[13px] font-medium leading-snug text-ds-ink shadow-sm transition hover:bg-ds-hover ${
    disabled ? 'cursor-not-allowed opacity-55' : ''
  }`
}
