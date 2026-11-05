import { Focus } from 'lucide-react'
import type { ReactElement } from 'react'
import { useTranslation } from 'react-i18next'

export function FocusModeToggle({
  active,
  onClick,
  className = ''
}: {
  active: boolean
  onClick: () => void
  className?: string
}): ReactElement {
  const { t } = useTranslation('common')
  return (
    <button
      type="button"
      onClick={onClick}
      className={`ds-focus-toggle-button ds-sidebar-toggle-button ds-no-drag shrink-0 ${
        active ? 'ds-focus-toggle-button--active' : ''
      } ${className}`.trim()}
      aria-label={t('focusModeToggle')}
      aria-pressed={active}
      title={t('focusModeToggle')}
    >
      <span className="ds-terminal-toggle__glyph" aria-hidden>
        <Focus className="h-4 w-4" strokeWidth={1.85} />
      </span>
    </button>
  )
}
