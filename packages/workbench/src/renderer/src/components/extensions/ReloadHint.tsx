import { useEffect, useState, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { RefreshCw } from 'lucide-react'

type Props = {
  /** Resolve `false` to skip the success flash (the caller reported instead). */
  onReload: () => Promise<boolean | void>
}

const MIN_SPIN_MS = 420

/** Icon-only reload control. Click spins in place; on success a short "list
 * refreshed" label flashes to the left of the icon, then clears. */
export function ReloadHint({ onReload }: Props): ReactElement {
  const { t } = useTranslation('common')
  const [status, setStatus] = useState<'idle' | 'loading' | 'done'>('idle')

  useEffect(() => {
    if (status !== 'done') return
    const timer = window.setTimeout(() => setStatus('idle'), 1600)
    return () => window.clearTimeout(timer)
  }, [status])

  const run = async (): Promise<void> => {
    if (status === 'loading') return
    setStatus('loading')
    const startedAt = Date.now()
    let ok = false
    try {
      ok = (await onReload()) !== false
    } catch {
      ok = false
    }
    const remaining = MIN_SPIN_MS - (Date.now() - startedAt)
    if (remaining > 0) await new Promise((resolve) => window.setTimeout(resolve, remaining))
    setStatus(ok ? 'done' : 'idle')
  }

  return (
    <button
      type="button"
      onClick={() => void run()}
      disabled={status === 'loading'}
      title={t('connectorReload')}
      aria-label={t('connectorReload')}
      className="ds-ext-reload-hint relative inline-flex h-8 w-8 items-center justify-center rounded-lg text-ds-muted transition-colors hover:bg-ds-hover hover:text-ds-ink disabled:cursor-default"
    >
      {status === 'done' ? (
        <span className="pointer-events-none absolute right-full mr-1.5 whitespace-nowrap text-[12px] font-medium text-emerald-600 dark:text-emerald-400">
          {t('listReloaded')}
        </span>
      ) : null}
      <RefreshCw
        className={`h-[18px] w-[18px] ${status === 'loading' ? 'animate-spin' : ''}`}
        strokeWidth={2}
      />
    </button>
  )
}
