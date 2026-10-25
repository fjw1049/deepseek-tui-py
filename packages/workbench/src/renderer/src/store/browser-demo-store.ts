import { create } from 'zustand'

/**
 * "Demonstrate to the agent" can start from the chat composer while the browser lives in
 * the sidebar: the composer files a request, the browser pane runs it and reports progress.
 */
type State = {
  /** Conversations whose browser is recording a demonstration. */
  active: Record<string, boolean>
  request: { threadId: string; id: number } | null
}

let nextRequest = 0
export const useBrowserDemoStore = create<State>(() => ({ active: {}, request: null }))

/** Start the demonstration, or finish the one already running. */
export function requestBrowserDemo(threadId: string): void {
  useBrowserDemoStore.setState({ request: { threadId, id: ++nextRequest } })
}

export function consumeBrowserDemoRequest(id: number): void {
  if (useBrowserDemoStore.getState().request?.id === id) useBrowserDemoStore.setState({ request: null })
}

export function setBrowserDemoActive(threadId: string, active: boolean): void {
  const current = useBrowserDemoStore.getState().active
  if (!!current[threadId] === active) return
  useBrowserDemoStore.setState({ active: { ...current, [threadId]: active } })
}
