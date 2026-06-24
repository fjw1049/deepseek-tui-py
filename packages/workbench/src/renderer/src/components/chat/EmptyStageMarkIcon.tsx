import type { ReactElement } from 'react'
import deepseekIcon from '../../../../asset/img/deepseek.png'

type Props = {
  className?: string
}

export function EmptyStageMarkIcon({ className = 'h-12 w-12' }: Props): ReactElement {
  return (
    <span
      className={['ds-empty-stage-mark inline-block shrink-0', className].join(' ')}
      style={{
        WebkitMaskImage: `url(${deepseekIcon})`,
        maskImage: `url(${deepseekIcon})`
      }}
      aria-hidden
    />
  )
}
