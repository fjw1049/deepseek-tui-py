import { useCallback, type ReactElement, type PointerEvent as ReactPointerEvent } from 'react'
import { createPortal } from 'react-dom'
import { PanelLeftOpen } from 'lucide-react'
import { useTranslation } from 'react-i18next'

type Props = {
  onExpand: () => void
}

export function SidebarExpandDroplet({ onExpand }: Props): ReactElement | null {
  const { t } = useTranslation('common')

  const handleActivate = useCallback(
    (event: ReactPointerEvent<HTMLButtonElement>) => {
      event.preventDefault()
      event.stopPropagation()
      onExpand()
    },
    [onExpand]
  )

  if (typeof document === 'undefined') return null

  return createPortal(
    <button
      type="button"
      onPointerDown={handleActivate}
      onClick={handleActivate}
      className="ds-sidebar-expand-droplet ds-no-drag"
      aria-label={t('sidebarExpand')}
      title={t('sidebarExpandShortcut')}
    >
      <PanelLeftOpen className="h-3.5 w-3.5" strokeWidth={2} />
    </button>,
    document.body
  )
}
