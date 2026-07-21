import type { ReactElement } from 'react'
import { Ban } from 'lucide-react'
import {
  SIDEBAR_LABEL_COLORS,
  type SidebarLabelColor
} from '../../lib/sidebar-chrome'

type ContextMenuColorBarProps = {
  value: SidebarLabelColor
  onChange: (color: SidebarLabelColor) => void
  clearLabel: string
}

export function ContextMenuColorBar({
  value,
  onChange,
  clearLabel
}: ContextMenuColorBarProps): ReactElement {
  return (
    <div className="flex items-center justify-between gap-1 px-2 py-1.5" role="group" aria-label={clearLabel}>
      <button
        type="button"
        className={`flex h-5 w-5 items-center justify-center rounded-full border transition-colors ${
          value == null
            ? 'border-ds-ink/35 bg-ds-hover text-ds-ink'
            : 'border-ds-border-muted text-ds-faint hover:border-ds-ink/25 hover:text-ds-muted'
        }`}
        title={clearLabel}
        aria-label={clearLabel}
        aria-pressed={value == null}
        onClick={() => onChange(null)}
      >
        <Ban className="h-3 w-3" strokeWidth={2} />
      </button>
      {SIDEBAR_LABEL_COLORS.map((color) => {
        const selected = value === color.id
        return (
          <button
            key={color.id}
            type="button"
            className={`h-5 w-5 rounded-full transition-transform ${
              selected ? 'scale-110 ring-2 ring-ds-ink/40 ring-offset-1 ring-offset-ds-elevated' : 'hover:scale-105'
            }`}
            style={{ backgroundColor: color.swatch }}
            title={color.id}
            aria-label={color.id}
            aria-pressed={selected}
            onClick={() => onChange(color.id)}
          />
        )
      })}
    </div>
  )
}
