import { type ReactElement, type ReactNode } from 'react'
import { Clock } from 'lucide-react'
import { useTranslation } from 'react-i18next'

const CARD_CLASS =
  'ds-automation-task-card ds-content-card ds-content-card--interactive relative flex min-h-[168px] flex-col rounded-xl p-6'

function CardToggle({
  checked,
  disabled,
  onChange
}: {
  checked: boolean
  disabled?: boolean
  onChange: () => void
}): ReactElement {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={(e) => {
        e.stopPropagation()
        onChange()
      }}
      className={`relative h-6 w-11 shrink-0 rounded-full transition-colors ${
        checked
          ? 'bg-emerald-500 shadow-sm'
          : 'border border-ds-border bg-neutral-300 shadow-inner dark:border-neutral-500 dark:bg-neutral-600'
      } ${disabled ? 'opacity-40' : 'cursor-pointer'}`}
    >
      <span
        className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${
          checked ? 'left-[22px]' : 'left-0.5'
        } ${checked ? '' : 'ring-1 ring-black/10 dark:ring-white/20'}`}
      />
    </button>
  )
}

export type AutomationListCardProps = {
  title: string
  preview: string
  schedule: string
  deliveryHint?: string
  deliveryTitle?: string
  leading?: ReactNode
  menu?: ReactNode
  groupHover?: boolean
  primaryAction: 'toggle' | 'button'
  active?: boolean
  actionBusy?: boolean
  actionLabel?: string
  onPrimaryAction: () => void
  onOpenDetails?: () => void
}

export function AutomationListCard({
  title,
  preview,
  schedule,
  deliveryHint,
  deliveryTitle,
  leading,
  menu,
  groupHover = false,
  primaryAction,
  active = false,
  actionBusy = false,
  actionLabel,
  onPrimaryAction,
  onOpenDetails
}: AutomationListCardProps): ReactElement {
  const { t } = useTranslation('common')

  return (
    <div className={groupHover ? `${CARD_CLASS} group` : CARD_CLASS}>
      <div className="flex min-h-0 flex-1 items-start gap-3">
        {leading}
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            {onOpenDetails ? (
              <button
                type="button"
                onClick={onOpenDetails}
                className="min-w-0 text-left"
              >
                <h3 className="truncate text-[15px] font-semibold text-ds-ink hover:text-accent">
                  {title}
                </h3>
              </button>
            ) : (
              <h3 className="min-w-0 truncate text-[15px] font-semibold text-ds-ink">{title}</h3>
            )}
            {menu}
          </div>
          <p className="mt-2 line-clamp-2 overflow-hidden text-[13px] leading-5 text-ds-muted">
            {preview}
          </p>
        </div>
      </div>
      <div className="mt-auto flex items-center gap-2 border-t border-ds-border-muted pt-3.5">
        <span className="flex min-w-0 flex-1 items-center gap-1.5 text-[13px] text-ds-faint">
          <Clock className="h-3.5 w-3.5 shrink-0" />
          <span className="truncate">{schedule}</span>
          {primaryAction === 'toggle' && !active ? (
            <span className="shrink-0 rounded bg-ds-subtle px-1.5 py-0.5 text-[11px] text-ds-muted">
              {t('automationPaused')}
            </span>
          ) : null}
        </span>
        {deliveryHint ? (
          <span
            className="max-w-[28%] shrink truncate text-[12px] text-ds-faint"
            title={deliveryTitle ?? deliveryHint}
          >
            {deliveryHint}
          </span>
        ) : null}
        {onOpenDetails ? (
          <button
            type="button"
            onClick={onOpenDetails}
            className="shrink-0 rounded-md border border-ds-border px-2 py-1 text-[12px] text-ds-muted hover:bg-ds-hover hover:text-ds-ink"
          >
            {t('automationDetailsAction')}
          </button>
        ) : null}
        {primaryAction === 'toggle' ? (
          <CardToggle checked={active} disabled={actionBusy} onChange={onPrimaryAction} />
        ) : (
          <button
            type="button"
            disabled={actionBusy}
            onClick={onPrimaryAction}
            className="shrink-0 rounded-lg bg-accent/10 px-3 py-1.5 text-[12px] font-medium text-accent transition hover:bg-accent/20 disabled:opacity-50"
          >
            {actionLabel}
          </button>
        )}
      </div>
    </div>
  )
}
