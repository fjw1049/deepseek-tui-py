/**
 * Warm common lazily-loaded views once the shell is idle.
 *
 * In dev, Vite transforms those chunk sources on demand, so a cold first
 * click blanked the main area for a noticeable beat. Leave rarer views on
 * demand so opening the app does not parse every feature in the background.
 *
 * WorkspaceEditorSurface (Monaco, ~7 MB) is deliberately NOT prefetched: it
 * is only needed once a file is actually opened for editing, and eager
 * evaluation would cost real memory and idle CPU for every user.
 */

type IdleWindow = Window & {
  requestIdleCallback?: (cb: () => void) => number
}

function runWhenIdle(task: () => void): void {
  const candidate = window as IdleWindow
  if (typeof candidate.requestIdleCallback === 'function') {
    candidate.requestIdleCallback(task)
    return
  }
  window.setTimeout(task, 300)
}

/** Remounts (Fast Refresh) must not restart prefetching. */
let started = false

export function prefetchLazyViews(): void {
  if (started) return
  started = true
  const loaders = [
    () => import('../components/SettingsView'),
    () => import('../components/kanban/KanbanView'),
    () => import('../components/chat/StreamdownAssistant')
  ]
  let index = 0
  const next = (): void => {
    if (index >= loaders.length) return
    runWhenIdle(() => {
      void loaders[index++]().catch(() => undefined).finally(next)
    })
  }
  next()
}
