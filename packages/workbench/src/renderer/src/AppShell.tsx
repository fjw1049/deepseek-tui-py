import { lazy, Suspense, useEffect, useState } from 'react'
import { useChatStore } from './store/chat-store'

const Workbench = lazy(() =>
  import('./components/Workbench').then((module) => ({ default: module.Workbench }))
)
const InitialSetupDialog = lazy(() =>
  import('./components/InitialSetupDialog').then((module) => ({
    default: module.InitialSetupDialog
  }))
)

type RevealPhase = 'waiting' | 'revealing' | 'live'

/** Longest child entrance (main 0.5s + 0.07s delay). */
const REVEAL_MS = 580

function StartupBlank({ exiting = false }: { exiting?: boolean }): React.ReactElement {
  return (
    <div
      className={`ds-startup-blank${exiting ? ' ds-startup-blank--exit' : ''}`}
      aria-hidden
    >
      <div className="ds-startup-breath" />
    </div>
  )
}

export default function AppShell(): React.ReactElement {
  const boot = useChatStore((s) => s.boot)
  const setStartupPhase = useChatStore((s) => s.setStartupPhase)
  const initialSetupOpen = useChatStore((s) => s.initialSetupOpen)
  const runtimeConnection = useChatStore((s) => s.runtimeConnection)
  const [revealPhase, setRevealPhase] = useState<RevealPhase>('waiting')

  // Codex-style gate: blank board until runtime settles (or setup / offline).
  const shellReady =
    initialSetupOpen ||
    runtimeConnection === 'ready' ||
    runtimeConnection === 'offline'

  useEffect(() => {
    // Prefetch the shell while the blank board is up so reveal isn't empty.
    void import('./components/Workbench')
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
      window.clearTimeout(timer)
      if (frame) window.cancelAnimationFrame(frame)
      unsubscribe?.()
    }
  }, [boot, setStartupPhase])

  useEffect(() => {
    if (!shellReady) {
      setRevealPhase('waiting')
      return
    }
    const reduced =
      typeof window !== 'undefined' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (reduced) {
      setRevealPhase('live')
      return
    }
    setRevealPhase('revealing')
    const timer = window.setTimeout(() => setRevealPhase('live'), REVEAL_MS)
    return () => window.clearTimeout(timer)
  }, [shellReady])

  const showBlank = revealPhase === 'waiting' || revealPhase === 'revealing'
  const showShell = shellReady

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
          <Suspense fallback={null}>
            <Workbench />
          </Suspense>
        </div>
      ) : null}
      {initialSetupOpen ? (
        <Suspense fallback={null}>
          <InitialSetupDialog />
        </Suspense>
      ) : null}
    </div>
  )
}
