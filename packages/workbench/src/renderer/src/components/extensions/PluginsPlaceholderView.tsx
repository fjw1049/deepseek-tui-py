import type { ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { Puzzle } from 'lucide-react'

export function PluginsPlaceholderView(): ReactElement {
  const { t } = useTranslation('common')
  return (
    <div className="ds-feature-page ds-page-scroll ds-no-drag flex min-h-0 flex-1 items-center justify-center overflow-y-auto px-6 py-7">
      <div className="ds-content-card flex max-w-md flex-col items-center rounded-2xl px-8 py-10 text-center">
        <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-ds-subtle text-ds-muted">
          <Puzzle className="h-7 w-7" strokeWidth={1.6} />
        </div>
        <h1 className="mt-5 text-[22px] font-semibold text-ds-ink">{t('extPlugins')}</h1>
        <p className="mt-2 text-[14px] leading-6 text-ds-muted">{t('pluginsComingSoon')}</p>
      </div>
    </div>
  )
}
