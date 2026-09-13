import type { ReactElement, ReactNode } from 'react'
import { AlertCircle, CheckCircle2, Info, TriangleAlert, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'

type Props = {
  tone: 'error' | 'warning' | 'success' | 'info'
  title?: string
  message: string
  details?: string
  actions?: ReactNode
  onDismiss?: () => void
}

/** Local feedback: semantic accent, readable summary, optional recovery and diagnostics. */
export function FeedbackNotice({ tone, title, message, details, actions, onDismiss }: Props): ReactElement {
  const { t } = useTranslation('common')
  const Icon = tone === 'error' ? AlertCircle : tone === 'warning' ? TriangleAlert : tone === 'success' ? CheckCircle2 : Info
  const accent = tone === 'error' ? 'text-red-700 dark:text-red-300'
    : tone === 'warning' ? 'text-amber-700 dark:text-amber-300'
      : tone === 'success' ? 'text-emerald-700 dark:text-emerald-300' : 'text-ds-muted'
  const longMessage = message.length > 160
  const detailText = longMessage ? [message, details].filter(Boolean).join('\n\n') : details
  return (
    <div role={tone === 'error' ? 'alert' : 'status'} className="flex min-w-0 items-start gap-2.5 rounded-xl border border-ds-border bg-ds-card px-3 py-3 text-[13px] leading-5 text-ds-ink">
      <Icon aria-hidden className={`mt-0.5 h-4 w-4 shrink-0 ${accent}`} />
      <div className="min-w-0 flex-1 [overflow-wrap:anywhere]">
        {title ? <p className="font-medium">{title}</p> : null}
        <p className={`${title ? 'mt-1 text-ds-muted' : ''} ${longMessage ? 'line-clamp-3' : ''}`}>{longMessage ? `${message.slice(0, 160)}…` : message}</p>
        {actions ? <div className="mt-2 flex flex-wrap items-center gap-2">{actions}</div> : null}
        {detailText ? (
          <details className="mt-2 text-ds-muted">
            <summary className="w-fit cursor-pointer rounded py-1 text-[12px]">{t('feedbackDetails')}</summary>
            <p className="mt-1 max-h-40 overflow-y-auto whitespace-pre-wrap">{detailText}</p>
          </details>
        ) : null}
      </div>
      {onDismiss ? <button type="button" aria-label={t('dismissNotice')} className="-mr-1 -mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-ds-muted hover:bg-ds-hover hover:text-ds-ink" onClick={onDismiss}><X aria-hidden className="h-4 w-4" /></button> : null}
    </div>
  )
}
