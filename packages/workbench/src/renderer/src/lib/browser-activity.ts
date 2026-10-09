export const BROWSER_ACTIVITY_EVENT = 'workbench:browser-activity'
const openedTurns = new Map<string, string>()

/** Only live, named tool starts reveal the browser; historical text never does. */
export function revealBrowserForTool(threadId: string, turnId: string | null, toolName: string | undefined, status: string): void {
  if (!turnId || toolName !== 'browser_use' || status !== 'running' || openedTurns.get(threadId) === turnId) return
  openedTurns.set(threadId, turnId)
  if (openedTurns.size > 100) openedTurns.delete(openedTurns.keys().next().value!)
  window.dispatchEvent(new CustomEvent(BROWSER_ACTIVITY_EVENT, { detail: { threadId } }))
}
