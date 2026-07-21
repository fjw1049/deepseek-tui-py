import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useShallow } from 'zustand/react/shallow'

import demoSpritesheet from '../../../asset/pet/demo-spritesheet.webp'
import { useChatStore } from '../store/chat-store'
import { resolvePetSpritesheetSrc } from '../lib/pet/pet-catalog'
import { subscribePetEvents, type PetActivityEvent } from '../lib/pet/pet-events'
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
import {
  resolvePetState,
  type PetActivityOverride,
  type PetBurst
} from '../lib/pet/pet-state-machine'
import type { PetStateId } from '../lib/pet/pet-states'

export type PetMascotStatus = 'ready' | 'fallback' | 'hidden'

const ROAM_MIN = -70
const ROAM_MAX = 70
/** Slow horizontal drift so idle roam reads as a stroll, not a dash. */
const ROAM_STEP = 0.4
const ROAM_TICK_MS = 120
const FAILED_HOLD_MS = 2200
const RESOLVED_BURST_MS = 700
const REASONING_HOLD_MS = 1200

const READ_LIKE_ACTIVITY = /\b(read|grep|glob|list_dir|search|find|cat)\b/i

function stateForToolActivity(event: {
  summary: string
  toolKind?: string
}): PetStateId {
  if (event.toolKind === 'file_change' || event.toolKind === 'command_execution') {
    return 'running'
  }
  return READ_LIKE_ACTIVITY.test(event.summary) ? 'review' : 'running'
}

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
  const [pageVisible, setPageVisible] = useState(() =>
    typeof document === 'undefined' ? true : !document.hidden
  )

  useEffect(() => {
    const onVisibilityChange = (): void => {
      setPageVisible(!document.hidden)
    }
    document.addEventListener('visibilitychange', onVisibilityChange)
    return () => document.removeEventListener('visibilitychange', onVisibilityChange)
  }, [])
  const revokeRef = useRef<(() => void) | null>(null)
  const [burst, setBurstState] = useState<PetBurst | null>(null)
  const [activityOverride, setActivityOverride] = useState<PetActivityOverride | null>(null)
  const [turnErrorActive, setTurnErrorActive] = useState(false)
  const lastStateRef = useRef<PetStateId>('idle')
  const lastChangeAtRef = useRef(0)
  const previousTurnIdRef = useRef<string | null>(null)
  const activeToolIdRef = useRef<string | null>(null)
  const activeSubagentIdRef = useRef<string | null>(null)

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
    const failFor = (durationMs = FAILED_HOLD_MS, persistent = true): void => {
      if (persistent) setTurnErrorActive(true)
      setActivityOverride({
        stateId: 'failed',
        priority: 'critical',
        expiresAt: Date.now() + durationMs
      })
    }

    const handleResolved = (
      status: 'allowed' | 'denied' | 'submitted' | 'cancelled' | 'error'
    ): void => {
      if (status === 'denied' || status === 'cancelled' || status === 'error') {
        failFor(FAILED_HOLD_MS, false)
        return
      }
      setActivityOverride(null)
      setBurst({ stateId: 'jumping', expiresAt: Date.now() + RESOLVED_BURST_MS })
    }

    return subscribePetEvents((event: PetActivityEvent) => {
      if (event.type === 'user_message') {
        activeToolIdRef.current = null
        activeSubagentIdRef.current = null
        setTurnErrorActive(false)
        setActivityOverride(null)
        setBurst({ stateId: 'jumping', expiresAt: Date.now() + 840 })
      } else if (event.type === 'agent_reasoning') {
        if (activeToolIdRef.current == null) {
          setActivityOverride({
            stateId: 'review',
            priority: 'sustained',
            expiresAt: Date.now() + REASONING_HOLD_MS
          })
        }
      } else if (event.type === 'tool_started') {
        activeToolIdRef.current = event.itemId
        setTurnErrorActive(false)
        setActivityOverride({
          stateId: stateForToolActivity(event),
          priority: 'sustained'
        })
      } else if (event.type === 'tool_completed') {
        if (event.status === 'error') {
          failFor()
        } else if (activeToolIdRef.current === event.itemId) {
          activeToolIdRef.current = null
          setActivityOverride(null)
        }
      } else if (
        event.type === 'approval_waiting' ||
        event.type === 'elevation_waiting' ||
        event.type === 'user_input_waiting'
      ) {
        setActivityOverride({ stateId: 'waiting', priority: 'critical' })
      } else if (event.type === 'approval_resolved' || event.type === 'elevation_resolved') {
        handleResolved(event.status)
      } else if (event.type === 'user_input_resolved') {
        handleResolved(event.status)
      } else if (event.type === 'subagent_started') {
        activeSubagentIdRef.current = event.itemId
        setActivityOverride({ stateId: 'running', priority: 'sustained' })
      } else if (event.type === 'subagent_completed') {
        if (event.status === 'failed' || event.status === 'cancelled') {
          failFor(FAILED_HOLD_MS, false)
        } else if (activeSubagentIdRef.current === event.itemId) {
          activeSubagentIdRef.current = null
          setActivityOverride(null)
        }
      } else if (event.type === 'turn_complete' || event.type === 'manual_wave') {
        activeToolIdRef.current = null
        activeSubagentIdRef.current = null
        setTurnErrorActive(false)
        setActivityOverride(null)
        setBurst({ stateId: 'waving', expiresAt: Date.now() + 700 })
      } else if (event.type === 'manual_jump') {
        setBurst({ stateId: 'jumping', expiresAt: Date.now() + 840 })
      } else if (event.type === 'turn_error') {
        failFor()
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
    setActivityOverride(null)
    activeToolIdRef.current = null
    activeSubagentIdRef.current = null
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

  useEffect(() => {
    if (!activityOverride?.expiresAt) return
    const delay = Math.max(0, activityOverride.expiresAt - Date.now())
    const timer = window.setTimeout(() => {
      setActivityOverride((current) => (current === activityOverride ? null : current))
    }, delay)
    return () => window.clearTimeout(timer)
  }, [activityOverride])

  const stateId = useMemo(() => {
    const now = Date.now()
    const next = resolvePetState({
      busy,
      blocks,
      liveReasoning,
      turnErrorActive,
      burst,
      activityOverride,
      now,
      lastState: lastStateRef.current,
      lastChangeAt: lastChangeAtRef.current
    })
    lastStateRef.current = next.stateId
    lastChangeAtRef.current = next.changedAt
    return next.stateId
  }, [activityOverride, busy, blocks, burst, liveReasoning, turnErrorActive])

  const visibleStatus: PetMascotStatus = enabled
    ? spritesheetSrc === demoSpritesheet
      ? 'fallback'
      : 'ready'
    : 'hidden'
  const canRoam =
    pageVisible && visibleStatus !== 'hidden' && stateId === 'idle' && burst == null && !busy

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

  // While roaming, always use the walk cycle — no center dead-zone that
  // snaps back to standing idle and makes the stroll flicker.
  const displayStateId = useMemo(() => {
    if (!canRoam) return stateId
    return roam.direction > 0 ? 'running-right' : 'running-left'
  }, [canRoam, roam.direction, stateId])

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
    roamOffset: canRoam ? roam.offset : 0,
    motionPaused: !pageVisible
  }
}
