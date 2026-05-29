import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useShallow } from 'zustand/react/shallow'

import demoSpritesheet from '../../../asset/pet/demo-spritesheet.webp'
import { useChatStore } from '../store/chat-store'
import { resolvePetSpritesheetSrc } from '../lib/pet/pet-catalog'
import { subscribePetEvents } from '../lib/pet/pet-events'
import {
  readPetEnabled,
  readPetSlug,
  subscribePetPreferences,
  writePetEnabled,
  writePetSlug
} from '../lib/pet/pet-preferences'
import {
  burstDurationMs,
  parsePetSlashCommand,
  type PetSlashAction
} from '../lib/pet/pet-slash-commands'
import { resolvePetState, type PetBurst } from '../lib/pet/pet-state-machine'
import type { PetStateId } from '../lib/pet/pet-states'

export type PetMascotStatus = 'ready' | 'fallback' | 'hidden'

const ROAM_MIN = -42
const ROAM_MAX = 42
const ROAM_STEP = 0.85
const ROAM_TICK_MS = 48

function applyPetSlashAction(
  action: PetSlashAction,
  enabled: boolean,
  setEnabled: (next: boolean) => void,
  setBurst: (burst: PetBurst) => void
): void {
  if (action.type === 'burst') {
    setBurst({
      stateId: action.stateId,
      expiresAt: Date.now() + burstDurationMs(action.stateId)
    })
    return
  }
  if (action.type === 'set_enabled') {
    setEnabled(action.enabled)
    return
  }
  setEnabled(!enabled)
}

export function usePetController() {
  const { busy, blocks, liveReasoning, currentTurnId } = useChatStore(
    useShallow((state) => ({
      busy: state.busy,
      blocks: state.blocks,
      liveReasoning: state.liveReasoning,
      currentTurnId: state.currentTurnId
    }))
  )

  const [enabled, setEnabledState] = useState(() => readPetEnabled())
  const [selectedSlug, setSelectedSlug] = useState(() => readPetSlug())
  const [spritesheetSrc, setSpritesheetSrc] = useState(demoSpritesheet)
  const [roam, setRoam] = useState({ offset: 0, direction: 1 as 1 | -1 })
  const revokeRef = useRef<(() => void) | null>(null)
  const [burst, setBurstState] = useState<PetBurst | null>(null)
  const [turnErrorActive, setTurnErrorActive] = useState(false)
  const lastStateRef = useRef<PetStateId>('idle')
  const lastChangeAtRef = useRef(0)
  const previousTurnIdRef = useRef<string | null>(null)

  const setBurst = useCallback(
    (burst: PetBurst) => {
      setBurstState(burst)
    },
    []
  )

  const applyFallbackSpritesheet = useCallback(() => {
    revokeRef.current?.()
    revokeRef.current = null
    setSpritesheetSrc(demoSpritesheet)
  }, [])

  const loadSpritesheet = useCallback(
    async (slug: string) => {
      try {
        const resolved = await resolvePetSpritesheetSrc(slug)
        revokeRef.current?.()
        revokeRef.current = resolved.revoke
        setSpritesheetSrc(resolved.src)
        setSelectedSlug(resolved.slug)
        writePetSlug(resolved.slug)
      } catch {
        applyFallbackSpritesheet()
      }
    },
    [applyFallbackSpritesheet]
  )

  useEffect(() => {
    void loadSpritesheet(readPetSlug())
    return () => revokeRef.current?.()
  }, [loadSpritesheet])

  useEffect(() => {
    return subscribePetPreferences(() => {
      const nextEnabled = readPetEnabled()
      const nextSlug = readPetSlug()
      setEnabledState(nextEnabled)
      setSelectedSlug((current) => {
        if (current !== nextSlug) {
          void loadSpritesheet(nextSlug)
        }
        return nextSlug
      })
    })
  }, [loadSpritesheet])

  useEffect(() => {
    return subscribePetEvents((kind) => {
      if (kind === 'user_message') {
        setTurnErrorActive(false)
        setBurst({ stateId: 'jumping', expiresAt: Date.now() + 840 })
      } else if (kind === 'turn_complete' || kind === 'wave') {
        setTurnErrorActive(false)
        setBurst({ stateId: 'waving', expiresAt: Date.now() + 700 })
      } else if (kind === 'jump') {
        setBurst({ stateId: 'jumping', expiresAt: Date.now() + 840 })
      } else if (kind === 'turn_error') {
        setTurnErrorActive(true)
      }
    })
  }, [setBurst])

  useEffect(() => {
    if (!currentTurnId || currentTurnId === previousTurnIdRef.current) {
      previousTurnIdRef.current = currentTurnId
      return
    }
    previousTurnIdRef.current = currentTurnId
    lastStateRef.current = 'idle'
    lastChangeAtRef.current = 0
    setTurnErrorActive(false)
    setRoam({ offset: 0, direction: 1 })
  }, [currentTurnId])

  useEffect(() => {
    if (!burst) return
    const delay = Math.max(0, burst.expiresAt - Date.now())
    const timer = window.setTimeout(() => {
      setBurstState((current) => (current === burst ? null : current))
    }, delay)
    return () => window.clearTimeout(timer)
  }, [burst])

  const stateId = useMemo(() => {
    const now = Date.now()
    const next = resolvePetState({
      busy,
      blocks,
      liveReasoning,
      turnErrorActive,
      burst,
      now,
      lastState: lastStateRef.current,
      lastChangeAt: lastChangeAtRef.current
    })
    lastStateRef.current = next.stateId
    lastChangeAtRef.current = next.changedAt
    return next.stateId
  }, [busy, blocks, burst, liveReasoning, turnErrorActive])

  const visibleStatus: PetMascotStatus = enabled
    ? spritesheetSrc === demoSpritesheet
      ? 'fallback'
      : 'ready'
    : 'hidden'
  const canRoam =
    visibleStatus !== 'hidden' && stateId === 'idle' && burst == null && !busy

  useEffect(() => {
    if (!canRoam) {
      setRoam({ offset: 0, direction: 1 })
      return
    }
    const timer = window.setInterval(() => {
      setRoam(({ offset, direction }) => {
        let nextOffset = offset + direction * ROAM_STEP
        let nextDirection = direction
        if (nextOffset >= ROAM_MAX) {
          nextOffset = ROAM_MAX
          nextDirection = -1
        } else if (nextOffset <= ROAM_MIN) {
          nextOffset = ROAM_MIN
          nextDirection = 1
        }
        return { offset: nextOffset, direction: nextDirection }
      })
    }, ROAM_TICK_MS)
    return () => window.clearInterval(timer)
  }, [canRoam])

  const displayStateId = useMemo(() => {
    if (!canRoam || Math.abs(roam.offset) < 4) return stateId
    return roam.direction > 0 ? 'running-right' : 'running-left'
  }, [canRoam, roam.direction, roam.offset, stateId])

  const setEnabled = useCallback(
    (next: boolean) => {
      setEnabledState(next)
      writePetEnabled(next)
    },
    []
  )

  const handlePetSlash = useCallback(
    (input: string): boolean => {
      const action = parsePetSlashCommand(input)
      if (!action) return false
      applyPetSlashAction(action, enabled, setEnabled, setBurst)
      return true
    },
    [enabled, setBurst, setEnabled]
  )

  return {
    stateId: displayStateId,
    spritesheetSrc,
    status: visibleStatus,
    enabled,
    selectedSlug,
    setEnabled,
    handlePetSlash,
    roamOffset: canRoam ? roam.offset : 0
  }
}
