import type { ReactElement } from 'react'
import { useTranslation } from 'react-i18next'

import type { PetMascotStatus } from '../../hooks/use-pet-controller'
import type { PetStateId } from '../../lib/pet/pet-states'
import { PetSprite } from './PetSprite'

type Props = {
  visible: boolean
  status: PetMascotStatus
  stateId: PetStateId
  spritesheetSrc: string
  scale?: number
  roamOffset?: number
}

export function PetMascotDock({
  visible,
  status,
  stateId,
  spritesheetSrc,
  scale = 0.23,
  roamOffset = 0
}: Props): ReactElement | null {
  const { t } = useTranslation('common')

  if (!visible || status === 'hidden') {
    return null
  }

  return (
    <div className="pet-mascot-shell relative flex w-full justify-center">
      <div className="pet-mascot-dock relative flex w-full items-end justify-center">
        <div className="relative flex flex-col items-center">
          <PetSprite
            src={spritesheetSrc}
            stateId={stateId}
            scale={scale}
            roamOffset={roamOffset}
            label={t('petMascotLabel')}
            className="pet-mascot-dock__sprite pointer-events-none"
          />
        </div>
      </div>
    </div>
  )
}
