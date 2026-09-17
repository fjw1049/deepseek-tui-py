/**
 * Warm the app's lazily-loaded feature chunks once the shell is up, so the
 * first open of Settings / Kanban / Marketplace / Automation / Channels (and
 * the chat renderer / right-rail panels) doesn't stall on a cold chunk.
 *
 * In dev, Vite transforms those chunk sources on demand, so a cold first
 * click blanked the main area for a noticeable beat; in production the same
 * click pays a smaller fetch-and-parse cost. Prefetching while idle removes
 * both — by the time the user clicks, the modules are already in cache and
 * the `lazy()` boundary resolves synchronously.
 *
 * WorkspaceEditorSurface (Monaco, ~7 MB) is deliberately NOT prefetched: it
 * is only needed once a file is actually opened for editing, and eager
 * evaluation would cost real memory and idle CPU for every user.
 */

const IDLE_TIMEOUT_MS = 4000

type IdleWindow = Window & {
  requestIdleCallback?: (cb: () => void, opts?: { timeout: number }) => number
}

function runWhenIdle(task: () => void): void {
  const candidate = window as IdleWindow
  if (typeof candidate.requestIdleCallback === 'function') {
    candidate.requestIdleCallback(task, { timeout: IDLE_TIMEOUT_MS })
    return
  }
  window.setTimeout(task, IDLE_TIMEOUT_MS)
}

/** Remounts (Fast Refresh) must not restart the prefetch waves. */
let started = false

export function prefetchLazyViews(): void {
  if (started) return
  started = true

  runWhenIdle(() => {
    // Sidebar destinations first — these are the routes users open from the
    // main interface.
    void import('../components/SettingsView')
    void import('../components/kanban/KanbanView')
    void import('../components/extensions/MarketplaceView')
    void import('../components/automation/AutomationCenter')
    void import('../components/channels/ChannelCenter')

    // Secondary surfaces once the routes are warm.
    runWhenIdle(() => {
      void import('../components/chat/StreamdownAssistant')
      void import('../components/right-sidebar/RunPanel')
      void import('../components/ChangeInspector')
      void import('../components/DevBrowserPanel')
      void import('../components/workspace-editor/WorkspaceEditorPanel')
      void import('../components/chat/tool/lazy-full-output')
    })
  })
}
