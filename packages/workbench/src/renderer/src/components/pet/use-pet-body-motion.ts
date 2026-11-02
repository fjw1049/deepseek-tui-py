import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent, type RefObject } from 'react'

import { readPetDockX, writePetDockX } from '../../lib/pet/pet-preferences'

/** Matches the slow walk cycle closely enough that the feet do not slide. */
export const PET_STROLL_SPEED_PX_S = 14
const FIRST_REST_MS: readonly [number, number] = [6000, 16_000]
const REST_MS: readonly [number, number] = [20_000, 60_000]
const LEG_MS: readonly [number, number] = [2000, 6000]
const MIN_LEG_PX = 12

export type PetStrollLeg = { to: number; durationMs: number }

const between = ([min, max]: readonly [number, number], random: () => number): number =>
  min + random() * (max - min)

export function nextPetRestMs(first: boolean, random: () => number = Math.random): number {
  return between(first ? FIRST_REST_MS : REST_MS, random)
}

/**
 * A short walk that stays inside the dock; null when there is no room for one.
 * Home is the right end (x = 0) and the pet may wander up to `span` px left of it.
 */
export function nextPetStrollLeg(
  x: number,
  span: number,
  random: () => number = Math.random
): PetStrollLeg | null {
  if (span < MIN_LEG_PX) return null
  const clamp = (value: number): number => Math.max(-span, Math.min(0, value))
  const distance = Math.max(MIN_LEG_PX, (between(LEG_MS, random) / 1000) * PET_STROLL_SPEED_PX_S)
  // Mostly wanders left from home, and heads back the further away it gets.
  const towardHome = random() < 0.1 + 0.8 * (-x / span)
  let to = clamp(x + (towardHome ? distance : -distance))
  if (Math.abs(to - x) < MIN_LEG_PX) to = clamp(x + (towardHome ? -distance : distance))
  if (Math.abs(to - x) < MIN_LEG_PX) return null
  return { to, durationMs: (Math.abs(to - x) / PET_STROLL_SPEED_PX_S) * 1000 }
}

function currentX(body: HTMLElement): number {
  const transform = getComputedStyle(body).transform
  if (!transform || transform === 'none') return 0
  return new DOMMatrixReadOnly(transform).m41
}

export type PetBodyMotion = {
  /** Walk direction while strolling or being dragged, else null. */
  direction: 1 | -1 | null
  dragging: boolean
  /** Drags the pet; a quick press that barely moves calls `onTap` instead. */
  onPointerDown: (event: ReactPointerEvent<HTMLElement>, onTap: () => void) => void
}

/**
 * Horizontal position of the pet inside its dock. It strolls now and then when
 * allowed, can be dragged, and stays wherever it stops: an interruption never
 * snaps it back home. Home is the right end of the dock; x is the offset left of it.
 */
export function usePetBodyMotion(
  bodyRef: RefObject<HTMLElement | null>,
  dockRef: RefObject<HTMLElement | null>,
  canStroll: boolean
): PetBodyMotion {
  const xRef = useRef(readPetDockX())
  const animationRef = useRef<Animation | null>(null)
  const [direction, setDirection] = useState<1 | -1 | null>(null)
  const [dragging, setDragging] = useState(false)

  const span = (): number => {
    const dock = dockRef.current
    const body = bodyRef.current
    if (!dock || !body) return 0
    return Math.max(0, dock.clientWidth - body.offsetWidth)
  }
  const clampX = (x: number): number => Math.max(-span(), Math.min(0, x))

  const place = (x: number): void => {
    xRef.current = x
    if (bodyRef.current) bodyRef.current.style.transform = `translateX(${x}px)`
  }

  const stopWalking = (): void => {
    const animation = animationRef.current
    const body = bodyRef.current
    if (!animation || !body) return
    const x = currentX(body)
    animation.cancel()
    animationRef.current = null
    place(x)
    setDirection(null)
  }

  // Keep the remembered spot reachable when the window or dock shrinks.
  useEffect(() => {
    const dock = dockRef.current
    const clamp = (): void => {
      const x = clampX(xRef.current)
      if (x !== xRef.current) place(x)
    }
    place(xRef.current)
    clamp()
    if (!dock || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(clamp)
    observer.observe(dock)
    return () => observer.disconnect()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!canStroll || dragging) {
      stopWalking()
      return
    }
    const body = bodyRef.current
    if (!body || typeof body.animate !== 'function') return
    let timer: number
    let first = true
    const rest = (): void => {
      timer = window.setTimeout(walk, nextPetRestMs(first))
      first = false
    }
    const walk = (): void => {
      const leg = nextPetStrollLeg(xRef.current, span())
      if (!leg) {
        rest()
        return
      }
      const from = xRef.current
      setDirection(leg.to > from ? 1 : -1)
      const animation = body.animate(
        [{ transform: `translateX(${from}px)` }, { transform: `translateX(${leg.to}px)` }],
        { duration: leg.durationMs, easing: 'linear' }
      )
      animationRef.current = animation
      animation.onfinish = () => {
        animationRef.current = null
        place(leg.to)
        setDirection(null)
        rest()
      }
    }
    rest()
    return () => {
      window.clearTimeout(timer)
      stopWalking()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canStroll, dragging])

  const onPointerDown = (event: ReactPointerEvent<HTMLElement>, onTap: () => void): void => {
    if (event.button !== 0) return
    const target = event.currentTarget
    try {
      target.setPointerCapture(event.pointerId)
    } catch {
      // A pointer that is already gone cannot be captured; the drag still works without it.
    }
    stopWalking()
    const startX = event.clientX
    const startY = event.clientY
    const origin = xRef.current
    const pressedAt = performance.now()
    let moved = false
    let lastX = startX

    const move = (next: PointerEvent): void => {
      const dx = next.clientX - startX
      if (!moved && Math.hypot(dx, next.clientY - startY) < 3) return
      if (!moved) {
        moved = true
        setDragging(true)
      }
      place(clampX(origin + dx))
      if (Math.abs(next.clientX - lastX) >= 1) setDirection(next.clientX > lastX ? 1 : -1)
      lastX = next.clientX
    }
    const up = (): void => {
      target.removeEventListener('pointermove', move)
      target.removeEventListener('pointerup', up)
      target.removeEventListener('pointercancel', up)
      if (moved) {
        writePetDockX(xRef.current)
        setDragging(false)
        setDirection(null)
      } else if (performance.now() - pressedAt <= 400) {
        onTap()
      }
    }
    target.addEventListener('pointermove', move)
    target.addEventListener('pointerup', up)
    target.addEventListener('pointercancel', up)
  }

  return { direction, dragging, onPointerDown }
}
