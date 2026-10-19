import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { MAX_BROWSER_SESSIONS, ensureBrowserSession, setPageDisplay, updatePageTab, useBrowserPagesStore } from './browser-pages-store'

beforeEach(() => { vi.useFakeTimers(); useBrowserPagesStore.setState({ sessions: {}, display: null }) })
afterEach(() => { vi.useRealTimers() })

it('closes the least recently used browsers beyond the limit, never the one on screen', () => {
  ensureBrowserSession('shown')
  setPageDisplay({ browserId: 'shown', rect: { top: 0, left: 0, width: 10, height: 10 } })
  for (let index = 0; index < MAX_BROWSER_SESSIONS; index += 1) {
    ensureBrowserSession(`thread-${index}`)
    vi.advanceTimersByTime(60_000)
  }
  // Page events in an old browser do not count as use.
  const old = useBrowserPagesStore.getState().sessions['thread-0']!
  updatePageTab('thread-0', old.activeTabId, { title: 'Busy page' })
  vi.advanceTimersByTime(10 * 60_000)
  ensureBrowserSession('newest')
  const kept = Object.keys(useBrowserPagesStore.getState().sessions)
  expect(kept).toHaveLength(MAX_BROWSER_SESSIONS)
  expect(kept).toContain('shown')
  expect(kept).not.toContain('thread-0')
})

it('keeps a browser used in the last ten minutes, which an agent may still be driving', () => {
  for (let index = 0; index <= MAX_BROWSER_SESSIONS; index += 1) ensureBrowserSession(`thread-${index}`)
  expect(Object.keys(useBrowserPagesStore.getState().sessions)).toHaveLength(MAX_BROWSER_SESSIONS + 1)
})

it('opens a page in a tab that is still attaching by starting a tab there instead', async () => {
  const { navigatePageTab } = await import('./browser-pages-store')
  const blank = ensureBrowserSession('one').activeTabId
  navigatePageTab('one', blank, 'http://localhost:5173/design.html', '/project/design.html')
  const session = useBrowserPagesStore.getState().sessions.one!
  expect(session.tabs).toHaveLength(1)
  expect(session.tabs[0]).toMatchObject({ url: 'http://localhost:5173/design.html', filePath: '/project/design.html' })
  expect(session.activeTabId).not.toBe(blank)
})
