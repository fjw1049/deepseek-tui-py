import { type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'
import { SharedCodeBlock } from './SharedCodeBlock'

type Props = {
  content: string
  actionsDisabled?: boolean
}

export function StructureBlock({ content, actionsDisabled = false }: Props): ReactElement {
  const { t } = useTranslation('common')
  return (
    <SharedCodeBlock
      code={content}
      title={t('structureBlockLabel')}
      actionsDisabled={actionsDisabled}
    />
  )
}
