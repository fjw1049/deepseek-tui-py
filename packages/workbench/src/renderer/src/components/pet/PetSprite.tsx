import { memo, useEffect, useRef, type CSSProperties } from 'react'

import {
  getPetStateDef,
  SPRITE_FRAME_H,
  SPRITE_FRAME_W,
  type PetStateId
} from '../../lib/pet/pet-states'

type Props = {
  src: string
  stateId?: PetStateId
  /** Change it to replay the same state from its first frame. */
  playKey?: number
  scale?: number
  label?: string
  className?: string
  motionPaused?: boolean
}

function prefersReducedMotion(): boolean {
  return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false
}

function PetSpriteImpl({
  src,
  stateId = 'idle',
  playKey = 0,
  scale = 1,
  label,
  className = '',
  motionPaused = false
}: Props) {
  const spriteRef = useRef<HTMLDivElement>(null)

  // Frames are written straight to the element: the sprite animates all the
  // time, and none of that should reach React.
  useEffect(() => {
    const sprite = spriteRef.current
    if (!sprite) return
    const { row, frameMs, once, restMs } = getPetStateDef(stateId)
    const paint = (frame: number): void => {
      sprite.style.backgroundPosition = `${-frame * SPRITE_FRAME_W}px ${-row * SPRITE_FRAME_H}px`
    }
    paint(0)
    if (motionPaused || prefersReducedMotion()) return

    let frame = 0
    let timer: number
    const advance = (): void => {
      const next = frame + 1
      if (next >= frameMs.length && once) return
      frame = next % frameMs.length
      paint(frame)
      const rest = frame === 0 && restMs
        ? restMs[0] + Math.random() * (restMs[1] - restMs[0])
        : 0
      timer = window.setTimeout(advance, frameMs[frame]! + rest)
    }
    timer = window.setTimeout(advance, frameMs[0]! + (restMs?.[0] ?? 0))
    return () => window.clearTimeout(timer)
  }, [motionPaused, playKey, stateId])

  return (
    <div
      className={`pet-sprite-frame ${className}`}
      role="img"
      aria-label={label ?? 'Pet animation'}
      style={{ '--pet-scale': scale } as CSSProperties}
    >
      <div
        ref={spriteRef}
        className="pet-sprite"
        style={{ '--sprite-url': `url("${src.replace(/"/g, '\\"')}")` } as CSSProperties}
      />
    </div>
  )
}

export const PetSprite = memo(PetSpriteImpl)
