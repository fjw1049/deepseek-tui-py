import { useEffect, useRef, type RefObject } from 'react'

/**
 * Electron titlebar drag regions (`-webkit-app-region: drag`) swallow pointer
 * events, so document outside-click listeners never fire on blank chrome.
 * While any light-dismiss surface is open we flip the shell to no-drag so
 * blank clicks reach JS and can close the surface.
 */
const LIGHT_DISMISS_CLASS = 'ds-light-dismiss-active'

let activeCount = 0

/** For non-React surfaces (e.g. reasoning-effort web component). */
export function beginLightDismissShell(): void {
  activeCount += 1
  if (activeCount === 1) {
    document.documentElement.classList.add(LIGHT_DISMISS_CLASS)
  }
}

/** Pair with {@link beginLightDismissShell}. */
export function endLightDismissShell(): void {
  activeCount = Math.max(0, activeCount - 1)
  if (activeCount === 0) {
    document.documentElement.classList.remove(LIGHT_DISMISS_CLASS)
  }
}

export type LightDismissTarget = RefObject<HTMLElement | null> | RefObject<Element | null>

type UseLightDismissOptions = {
  open: boolean
  onDismiss: () => void
  /** Trigger + panel roots; clicks inside these do not dismiss. */
  refs: readonly LightDismissTarget[]
  /** When false, skip attaching (e.g. disabled control). Default true. */
  enabled?: boolean
}

/**
 * Standard light-dismiss for main-workbench menus / pickers / popovers:
 * capture-phase outside pointerdown + Escape, with Electron drag unlocked.
 */
export function useLightDismiss({
  open,
  onDismiss,
  refs,
  enabled = true
}: UseLightDismissOptions): void {
  const refsRef = useRef(refs)
  refsRef.current = refs
  const onDismissRef = useRef(onDismiss)
  onDismissRef.current = onDismiss

  useEffect(() => {
    if (!open || !enabled) return

    beginLightDismissShell()

    const isInside = (target: EventTarget | null): boolean => {
      if (!(target instanceof Node)) return false
      for (const ref of refsRef.current) {
        if (ref.current?.contains(target)) return true
      }
      return false
    }

    const onPointerDown = (event: PointerEvent): void => {
      if (isInside(event.target)) return
      onDismissRef.current()
    }

    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key !== 'Escape') return
      event.preventDefault()
      onDismissRef.current()
    }

    // Defer so the opening click cannot immediately dismiss.
    const timer = window.setTimeout(() => {
      window.addEventListener('pointerdown', onPointerDown, true)
    }, 0)
    window.addEventListener('keydown', onKeyDown)

    return () => {
      window.clearTimeout(timer)
      window.removeEventListener('pointerdown', onPointerDown, true)
      window.removeEventListener('keydown', onKeyDown)
      endLightDismissShell()
    }
  }, [open, enabled])
}
