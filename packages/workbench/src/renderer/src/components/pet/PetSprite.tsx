import { memo, type CSSProperties } from 'react'

import { getPetStateDef, type PetStateId } from '../../lib/pet/pet-states'

type Props = {
  src: string
  stateId?: PetStateId
  scale?: number
  roamOffset?: number
  label?: string
  className?: string
}

function PetSpriteImpl({
  src,
  stateId = 'idle',
  scale = 1,
  roamOffset = 0,
  label,
  className = ''
}: Props) {
  const animation = getPetStateDef(stateId)

  return (
    <div
      className={`pet-sprite-frame ${className}`}
      role="img"
      aria-label={label ?? 'Pet animation'}
      style={
        {
          '--pet-scale': scale,
          '--pet-roam-offset': `${roamOffset}px`
        } as CSSProperties
      }
    >
      <div
        className="pet-sprite"
        style={
          {
            '--sprite-url': `url("${src.replace(/"/g, '\\"')}")`,
            '--sprite-row': animation.row,
            '--sprite-frames': animation.frames,
            '--sprite-duration': `${animation.durationMs}ms`
          } as CSSProperties
        }
      />
    </div>
  )
}

export const PetSprite = memo(PetSpriteImpl)
