// @vitest-environment happy-dom
import { expect, it, vi } from 'vitest'
import { BROWSER_ACTIVITY_EVENT, revealBrowserForTool } from './browser-activity'
it('reveals once per live browser turn and ignores other tools and restored text', () => {
  const listener = vi.fn()
  window.addEventListener(BROWSER_ACTIVITY_EVENT, listener)
  try {
    revealBrowserForTool('thread', null, 'browser_use', 'running')
    revealBrowserForTool('thread', 'turn1', 'shell', 'running')
    revealBrowserForTool('thread', 'turn1', undefined, 'success')
    expect(listener).not.toHaveBeenCalled()
    revealBrowserForTool('thread', 'turn1', 'browser_use', 'running')
    revealBrowserForTool('thread', 'turn1', 'browser_use', 'running')
    expect(listener).toHaveBeenCalledTimes(1)
    revealBrowserForTool('thread', 'turn2', 'browser_use', 'running')
    expect(listener).toHaveBeenCalledTimes(2)
  } finally { window.removeEventListener(BROWSER_ACTIVITY_EVENT, listener) }
})
