import type { ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import appIconUrl from '../../assets/brand/app-icon.svg'

type Props = {
  className?: string
}

/** Simple empty-home greeting: brand mark + one centered line. */
export function SimpleEmptyPrompt({ className = '' }: Props): ReactElement {
  const { t } = useTranslation('common')

  return (
    <div className={`ds-simple-empty-prompt ${className}`.trim()}>
      <img
        src={appIconUrl}
        alt=""
        draggable={false}
        className="ds-simple-empty-prompt__icon"
        aria-hidden
      />
      <h1 className="ds-simple-empty-prompt__title">{t('emptyStagePrompt')}</h1>
    </div>
  )
}
