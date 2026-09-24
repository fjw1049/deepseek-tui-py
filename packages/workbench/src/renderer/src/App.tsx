import { Component, lazy, Suspense, type ReactNode } from 'react'
import i18n from './i18n'
import { StartupWindowDragRegions } from './components/StartupWindowDragRegions'

const AppShell = lazy(() => import('./AppShell'))

class AppErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError(): { failed: boolean } {
    return { failed: true }
  }

  componentDidCatch(error: Error): void {
    console.error('[Workbench] interface error:', error)
  }

  render(): ReactNode {
    if (!this.state.failed) return this.props.children
    return (
      <div className="ds-app-root flex h-full min-h-0 flex-col items-center justify-center gap-4 bg-ds-main px-6 text-center text-ds-ink" role="alert">
        <p>{i18n.t('common:appRenderError')}</p>
        <button type="button" className="rounded-xl bg-accent px-4 py-2 text-white" onClick={() => window.location.reload()}>
          {i18n.t('common:reloadApp')}
        </button>
      </div>
    )
  }
}

function StartupShell(): React.ReactElement {
  return (
    <div className="ds-app-root ds-no-drag relative flex h-full min-h-0 items-center justify-center bg-transparent text-ds-muted">
      <StartupWindowDragRegions />
      <div className="ds-glass flex items-center gap-2 rounded-full px-4 py-2 text-[13px]">
        <span className="h-2 w-2 animate-pulse rounded-full bg-accent" aria-hidden />
        <span>Loading DeepSeek GUI...</span>
      </div>
    </div>
  )
}

export default function App(): React.ReactElement {
  return (
    <AppErrorBoundary>
      <Suspense fallback={<StartupShell />}>
        <AppShell />
      </Suspense>
    </AppErrorBoundary>
  )
}
