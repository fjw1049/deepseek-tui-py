import type { ReactElement } from 'react'
import { Bot } from 'lucide-react'
import { useTranslation } from 'react-i18next'

type OfflineProps = {
  onRetry: () => void
  onOpenSettings: () => void
  onOpenDiagnostics: () => void
}

export function TaskSuggestionOfflineHero({
  onRetry,
  onOpenSettings,
  onOpenDiagnostics
}: OfflineProps): ReactElement {
  const { t } = useTranslation('common')
  return (
    <div className="flex flex-col items-center justify-center px-8 py-16 text-center">
      <div className="ds-card-soft mb-4 rounded-[12px] px-4 py-3">
        <Bot className="mx-auto h-6 w-6 text-accent opacity-90" strokeWidth={1.4} />
      </div>
      <p className="max-w-sm text-[20px] font-semibold tracking-[-0.03em] text-ds-ink">
        {t('runtimeOfflineHeroTitle')}
      </p>
      <p className="mt-2 max-w-[520px] text-[14px] leading-6 text-ds-muted">{t('runtimeOfflineHeroSub')}</p>
      <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
        <button
          type="button"
          className="ds-chip rounded-full px-4 py-2 text-[12.5px] font-medium text-ds-ink"
          onClick={onRetry}
        >
          {t('retryConnection')}
        </button>
        <button
          type="button"
          className="ds-chip-muted rounded-full px-4 py-2 text-[12.5px] font-medium text-ds-muted"
          onClick={onOpenDiagnostics}
        >
          {t('runtimeDiagnosticsButton')}
        </button>
        <button
          type="button"
          className="ds-chip-muted rounded-full px-4 py-2 text-[12.5px] font-medium text-ds-muted"
          onClick={onOpenSettings}
        >
          {t('openSettings')}
        </button>
      </div>
    </div>
  )
}
