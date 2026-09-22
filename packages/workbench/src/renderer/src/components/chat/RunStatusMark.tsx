import { CheckCircle2, CircleDashed, CircleMinus, CircleX, Clock, Loader2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { runStatusKey } from '../../lib/run-activity'

/** Shared status vocabulary for conversation entries and the activity dock. */
export function RunStatusMark({ status }: { status: string }): React.JSX.Element {
  const { t } = useTranslation('common')
  const label = t(runStatusKey(status))
  const Icon = status === 'running' ? Loader2 : status === 'completed' ? CheckCircle2
    : status === 'failed' ? CircleX : status === 'timed_out' ? Clock
      : status === 'canceled' || status === 'cancelled' ? CircleMinus : CircleDashed
  const color = status === 'completed' ? 'text-emerald-600 dark:text-emerald-400'
    : status === 'failed' || status === 'timed_out' ? 'text-red-600 dark:text-red-400' : 'text-ds-muted'
  return (
    <span role="img" aria-label={label} title={label} data-status={status} className={`inline-flex shrink-0 items-center ${color}`}>
      <Icon aria-hidden className={`h-3.5 w-3.5 ${status === 'running' ? 'animate-spin motion-reduce:animate-none' : ''}`} strokeWidth={1.8} />
    </span>
  )
}
