import { useId, useRef, type ReactNode } from 'react'
import { X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useModalFocus } from '../../hooks/use-modal-focus'
import { PluginIcon } from './PluginIcon'

export function PluginDialog({ pluginId, title, summary, onClose, children }: {
  pluginId: string
  title: string
  summary: string
  onClose: () => void
  children: ReactNode
}): React.JSX.Element {
  const { t } = useTranslation('common')
  const ref = useRef<HTMLDivElement>(null)
  const titleId = useId()
  useModalFocus(true, ref, onClose)
  return <div className="ds-no-drag fixed inset-0 z-[90] flex items-center justify-center bg-black/25 p-5 dark:bg-black/50"
    onClick={event => { if (event.target === event.currentTarget) onClose() }}>
    <div ref={ref} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}
      className="relative max-h-[85vh] w-full max-w-[640px] overflow-y-auto rounded-2xl border border-ds-border bg-ds-card p-7 text-ds-ink shadow-xl">
      <button type="button" onClick={onClose} aria-label={t('pluginCloseDetail')}
        className="absolute right-4 top-4 rounded-lg p-2 text-ds-muted hover:bg-ds-hover"><X className="size-4" /></button>
      <PluginIcon pluginId={pluginId} />
      <h2 id={titleId} className="mt-4 text-xl font-semibold">{title}</h2>
      <p className="mt-2 text-sm leading-6 text-ds-muted">{summary}</p>
      {children}
    </div>
  </div>
}
