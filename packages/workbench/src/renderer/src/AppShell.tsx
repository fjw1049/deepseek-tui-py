import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { useChatStore } from './store/chat-store'
import i18n from './i18n'
import { StartupWindowDragRegions } from './components/StartupWindowDragRegions'

const Workbench = lazy(() =>
  import('./components/Workbench').then((module) => ({ default: module.Workbench }))
)
const KineticGrid = lazy(() =>
  import('./components/KineticGrid').then((module) => ({ default: module.KineticGrid }))
)

type RevealPhase = 'waiting' | 'revealing' | 'live'

/** Longest child entrance (main 0.5s + 0.07s delay). */
const REVEAL_MS = 580

/** Blank board fade-out (matches ds-startup-blank-exit in index.css). Once it
 *  finishes the board is unmounted, even though the shell keeps entering — so
 *  there's no transparent-but-mounted board lingering on top after the
 *  kinetic grid has faded. */
const BLANK_EXIT_MS = 200

/** A brief entrance keeps a fast handshake from flashing the board. */
const MIN_BLANK_MS = 300

/**
 * Survives Vite Fast Refresh / HMR remounts of this module. Without this, every
 * AppShell hot update replays the kinetic-grid blank board and feels like a full
 * app restart back to the greeting screen.
 */
let coldStartCeremonyDone = false

function StartupBlank({ exiting = false }: { exiting?: boolean }): React.ReactElement {
  return (
    <div
      className={`ds-startup-blank${exiting ? ' ds-startup-blank--exit' : ''}`}
      aria-hidden
    >
      <Suspense fallback={null}>
        <KineticGrid />
      </Suspense>
      <StartupWindowDragRegions />
    </div>
  )
}

export default function AppShell(): React.ReactElement {
  const boot = useChatStore((s) => s.boot)
  const setStartupPhase = useChatStore((s) => s.setStartupPhase)
  const initialSetupOpen = useChatStore((s) => s.initialSetupOpen)
  const runtimeConnection = useChatStore((s) => s.runtimeConnection)
  const [revealPhase, setRevealPhase] = useState<RevealPhase>(
    coldStartCeremonyDone ? 'live' : 'waiting'
  )
  const [shellModulesReady, setShellModulesReady] = useState(coldStartCeremonyDone)
  const [blankGone, setBlankGone] = useState(coldStartCeremonyDone)
  /** Once true, the cold-start ceremony never runs again — reconnect/checking
   *  must not unmount Workbench or replay the kinetic grid. */
  const [startupGateDone, setStartupGateDone] = useState(coldStartCeremonyDone)
  const gateStartedRef = useRef(coldStartCeremonyDone)
  const mountedAtRef = useRef<number>(performance.now())
  const timersRef = useRef<{ hold: number; blank: number; reveal: number }>({
    hold: 0,
    blank: 0,
    reveal: 0
  })

  // First-enter gate only: runtime settled (or setup / offline). After
  // startupGateDone, runtimeConnection may go through 'checking' without
  // tearing down the shell.
  const canEnterShell =
    shellModulesReady &&
    (initialSetupOpen || runtimeConnection === 'ready' || runtimeConnection === 'offline')

  useEffect(() => {
    // Prefetch shell + kinetic grid while the blank board is up so reveal isn't empty
    // and the mesh is ready before MIN_BLANK_MS elapses on a fast handshake.
    let cancelled = false
    // Workbench statically imports navigation pages: revealing it means those
    // components are ready too, with no first-click lazy boundary.
    void import('./components/Workbench').then(
      () => { if (!cancelled) setShellModulesReady(true) },
      // Let the render error boundary report a failed import instead of hanging.
      () => { if (!cancelled) setShellModulesReady(true) }
    )
    void import('./components/chat/StreamdownAssistant').catch(() => undefined)
    void import('./components/KineticGrid')
    if (typeof window.dsGui?.getStartupPhase === 'function') {
      void window.dsGui.getStartupPhase().then(setStartupPhase).catch(() => undefined)
    }
    const unsubscribe =
      typeof window.dsGui?.onStartupPhase === 'function'
        ? window.dsGui.onStartupPhase(setStartupPhase)
        : undefined
    let frame = 0
    const timer = window.setTimeout(() => {
      frame = window.requestAnimationFrame(() => {
        void boot()
      })
    }, 0)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
      if (frame) window.cancelAnimationFrame(frame)
      unsubscribe?.()
    }
  }, [boot, setStartupPhase])

  useEffect(() => {
    if (startupGateDone || gateStartedRef.current || !canEnterShell) return
    gateStartedRef.current = true

    const reduced =
      typeof window !== 'undefined' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reduced) {
      coldStartCeremonyDone = true
      setRevealPhase('live')
      setBlankGone(true)
      setStartupGateDone(true)
      return
    }

    // Hold the board (and its kinetic grid) until MIN_BLANK_MS has elapsed, so a
    // fast runtime handshake doesn't flash the animation for a single frame.
    const heldFor = performance.now() - mountedAtRef.current
    const holdRemaining = Math.max(0, MIN_BLANK_MS - heldFor)
    const timers = timersRef.current
    timers.hold = window.setTimeout(() => {
      setRevealPhase('revealing')
      // Unmount the board as soon as its own fade finishes, so it doesn't sit
      // (transparent) on top while the shell finishes entering underneath.
      timers.blank = window.setTimeout(() => setBlankGone(true), BLANK_EXIT_MS)
      timers.reveal = window.setTimeout(() => {
        coldStartCeremonyDone = true
        setRevealPhase('live')
        setStartupGateDone(true)
      }, REVEAL_MS)
    }, holdRemaining)
  }, [canEnterShell, startupGateDone])

  useEffect(() => {
    return () => {
      const timers = timersRef.current
      if (timers.hold) window.clearTimeout(timers.hold)
      if (timers.blank) window.clearTimeout(timers.blank)
      if (timers.reveal) window.clearTimeout(timers.reveal)
    }
  }, [])

  const showBlank =
    !startupGateDone && !blankGone && (revealPhase === 'waiting' || revealPhase === 'revealing')
  const showShell = startupGateDone || canEnterShell

  return (
    <div className="ds-app-root ds-app-root--startup h-full min-h-0 bg-transparent">
      {showBlank ? <StartupBlank exiting={revealPhase === 'revealing'} /> : null}
      {showShell ? (
        <div
          className={[
            'ds-startup-stage',
            revealPhase === 'revealing' ? 'ds-startup-stage--enter' : '',
            revealPhase === 'live' ? 'ds-startup-stage--live' : ''
          ]
            .filter(Boolean)
            .join(' ')}
        >
          <Suspense fallback={<div className="flex h-full items-center justify-center text-ds-muted" role="status">{i18n.t('common:startupRenderer')}</div>}>
            <Workbench />
          </Suspense>
        </div>
      ) : null}
    </div>
  )
}
