import { lazy, Suspense, useEffect } from 'react'
import { useChatStore } from './store/chat-store'

const Workbench = lazy(() =>
  import('./components/Workbench').then((module) => ({ default: module.Workbench }))
)
const SettingsView = lazy(() =>
  import('./components/SettingsView').then((module) => ({ default: module.SettingsView }))
)
const InitialSetupDialog = lazy(() =>
  import('./components/InitialSetupDialog').then((module) => ({
    default: module.InitialSetupDialog
  }))
)

function RouteFallback(): React.ReactElement {
  return <div className="h-full bg-ds-main" />
}

export default function AppShell(): React.ReactElement {
  const route = useChatStore((s) => s.route)
  const boot = useChatStore((s) => s.boot)
  const setStartupPhase = useChatStore((s) => s.setStartupPhase)
  const initialSetupOpen = useChatStore((s) => s.initialSetupOpen)

  useEffect(() => {
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

  return (
    <div className="h-full min-h-0 bg-transparent">
      <Suspense fallback={<RouteFallback />}>
        {route === 'settings' ? <SettingsView /> : <Workbench />}
      </Suspense>
      {initialSetupOpen ? (
        <Suspense fallback={null}>
          <InitialSetupDialog />
        </Suspense>
      ) : null}
    </div>
  )
}
