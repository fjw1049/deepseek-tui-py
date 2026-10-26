import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { BLANK_PAGE, MAX_BROWSER_SESSIONS, setBrowserInputBlocked, retainBrowserSession, openPageTab, closePageTab, navigatePageTab, ensureBrowserSession, setPageDisplay, updatePageTab, useBrowserPagesStore } from './browser-pages-store'

beforeEach(() => { vi.useFakeTimers(); useBrowserPagesStore.setState({ sessions: {}, display: null }) })
afterEach(() => { vi.useRealTimers() })

it('prunes unused blank browsers before ones showing pages', () => {
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
  expect(kept).toContain('thread-0')
  expect(kept).not.toContain('thread-1')
})

it('caps browsers with pages too and reopens their URLs when the conversation returns', () => {
  for (let index = 0; index < MAX_BROWSER_SESSIONS; index += 1) {
    openPageTab(`thread-${index}`, `https://example.test/${index}`)
    vi.advanceTimersByTime(60_000)
  }
  const old = useBrowserPagesStore.getState().sessions['thread-0']!
  updatePageTab('thread-0', old.activeTabId, { title: 'Draft' })
  vi.advanceTimersByTime(10 * 60_000)
  openPageTab('newest', 'https://example.test/new')
  const { sessions } = useBrowserPagesStore.getState()
  expect(Object.keys(sessions)).toHaveLength(MAX_BROWSER_SESSIONS)
  expect(sessions['thread-0']).toBeUndefined()
  const reopened = ensureBrowserSession('thread-0')
  expect(reopened.tabs.map(tab => tab.url)).toEqual([BLANK_PAGE, 'https://example.test/0'])
  expect(reopened.tabs.find(tab => tab.id === reopened.activeTabId)).toMatchObject({ url: 'https://example.test/0', title: 'Draft', loading: true })
  expect(reopened.tabs.every(tab => !old.tabs.some(previous => previous.id === tab.id))).toBe(true)
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


it('protects a connected background browser across tab changes until its runtime releases it', () => {
  ensureBrowserSession('running')
  expect(retainBrowserSession('running', true)).toBe(true)
  const tab = openPageTab('running', 'https://example.test/')
  navigatePageTab('running', tab, 'https://example.test/next')
  closePageTab('running', useBrowserPagesStore.getState().sessions.running!.activeTabId, 'runtime')
  for (let i = 0; i < 7; i++) ensureBrowserSession(`other-${i}`)
  vi.advanceTimersByTime(11 * 60_000)
  ensureBrowserSession('ninth')
  expect(useBrowserPagesStore.getState().sessions.running).toBeDefined()
  retainBrowserSession('running', false)
  ensureBrowserSession('tenth')
  expect(useBrowserPagesStore.getState().sessions.running).toBeUndefined()
})


it('guards the tab being closed while keeping runtime closes and user takeover working', () => {
  const agentTab = ensureBrowserSession('one').activeTabId
  const userTab = openPageTab('one', 'https://example.test/')
  setBrowserInputBlocked('one', true, agentTab)
  expect(closePageTab('one', agentTab)).toBe(false)
  expect(closePageTab('one', userTab)).toBe(true)
  expect(closePageTab('one', agentTab, 'runtime')).toBe(true)
  const replacement = useBrowserPagesStore.getState().sessions.one!.activeTabId
  setBrowserInputBlocked('one', true)
  expect(closePageTab('one', replacement)).toBe(false)
  setBrowserInputBlocked('one', false)
  expect(closePageTab('one', replacement)).toBe(true)
})
