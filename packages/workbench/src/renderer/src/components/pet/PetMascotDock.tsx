import { useEffect, useRef, type CSSProperties, type ReactElement } from 'react'
import { useTranslation } from 'react-i18next'

import type { PetBubble } from '../../hooks/use-pet-controller'
import type { PetStateId } from '../../lib/pet/pet-states'
import { PetSprite } from './PetSprite'
import { usePetBodyMotion } from './use-pet-body-motion'

const HOVER_DELAY_MS = 200
const HEARTS = [
  { x: '-14px', size: '10px', delay: '0ms' },
  { x: '4px', size: '13px', delay: '160ms' },
  { x: '-4px', size: '9px', delay: '420ms' },
  { x: '10px', size: '11px', delay: '700ms' },
  { x: '-12px', size: '12px', delay: '980ms' }
] as const

type Props = {
  stateId: PetStateId
  playKey: number
  spritesheetSrc: string
  petName: string
  bubble: PetBubble | null
  hearts: number
  canStroll: boolean
  motionPaused?: boolean
  scale?: number
  onActivate: () => void
  onHoverChange: (hovered: boolean) => void
  onBubbleAction: (bubble: PetBubble) => void
}

export function PetMascotDock({
  stateId,
  playKey,
  spritesheetSrc,
  petName,
  bubble,
  hearts,
  canStroll,
  motionPaused = false,
  scale = 0.23,
  onActivate,
  onHoverChange,
  onBubbleAction
}: Props): ReactElement {
  const { t } = useTranslation('common')
  const dockRef = useRef<HTMLDivElement>(null)
  const moverRef = useRef<HTMLDivElement>(null)
  const hoverTimer = useRef<number | undefined>(undefined)
  const motion = usePetBodyMotion(moverRef, dockRef, canStroll && !motionPaused)

  useEffect(() => () => window.clearTimeout(hoverTimer.current), [])

  const walking = motion.direction != null && (motion.dragging || stateId === 'idle')
  const shownState: PetStateId = walking
    ? motion.direction === 1 ? 'running-right' : 'running-left'
    : stateId

  const hover = (inside: boolean): void => {
    window.clearTimeout(hoverTimer.current)
    // Entering waits a moment so a cursor passing through does not open it; leaving is immediate.
    if (inside) hoverTimer.current = window.setTimeout(() => onHoverChange(true), HOVER_DELAY_MS)
    else onHoverChange(false)
  }

  return (
    <div className="pet-mascot-shell relative flex w-full justify-end">
      <div ref={dockRef} className="pet-mascot-dock relative flex w-full items-end justify-end">
        {/* The mover carries the position; bubble and hearts ride along with the pet. */}
        <div ref={moverRef} className="pet-mascot-mover">
          {bubble ? (
            <button
              key={bubble.key}
              type="button"
              className={[
                'pet-mascot-bubble',
                bubble.sticky ? '' : 'pet-mascot-bubble--timed',
                bubble.action ? 'pet-mascot-bubble--action' : '',
                bubble.nudge ? 'pet-mascot-bubble--nudge' : ''
              ].join(' ')}
              aria-live={bubble.sticky ? 'polite' : 'off'}
              onPointerDown={(event) => event.stopPropagation()}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => onBubbleAction(bubble)}
            >
              {bubble.text}
            </button>
          ) : null}
          {hearts > 0 ? (
            <span key={hearts} className="pet-mascot-hearts" aria-hidden="true">
              {HEARTS.map((heart, index) => (
                <span
                  key={index}
                  className="pet-mascot-heart"
                  style={{
                    '--heart-x': heart.x,
                    '--heart-size': heart.size,
                    '--heart-delay': heart.delay
                  } as CSSProperties}
                >
                  ♥
                </span>
              ))}
            </span>
          ) : null}
          <div
            className={`pet-mascot-body ds-no-drag ${motion.dragging ? 'pet-mascot-body--dragging' : ''}`}
            role="button"
            tabIndex={0}
            aria-label={t('petMascotActivate', { name: petName })}
            onPointerDown={(event) => motion.onPointerDown(event, onActivate)}
            // Keep the composer focused: the pet is clicked, not focused.
            onMouseDown={(event) => event.preventDefault()}
            onPointerEnter={() => hover(true)}
            onPointerLeave={() => hover(false)}
            onKeyDown={(event) => {
              if (event.key !== 'Enter' && event.key !== ' ') return
              event.preventDefault()
              onActivate()
            }}
          >
            <PetSprite
              src={spritesheetSrc}
              stateId={shownState}
              playKey={playKey}
              scale={scale}
              label={petName}
              className="pet-mascot-dock__sprite"
              motionPaused={motionPaused}
            />
          </div>
        </div>
      </div>
    </div>
  )
}
