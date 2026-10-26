// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { beforeEach, expect, it, vi } from 'vitest'
import type { BrowserBridgeCommand } from '@shared/browser-bridge'
import { BrowserPageLayer } from './BrowserPageLayer'
import { openPageTab, setPageDisplay, useBrowserPagesStore } from '../store/browser-pages-store'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
beforeEach(() => { useBrowserPagesStore.setState({ sessions: {}, display: null }) })

function mount() {
  let command: ((requestId: string, command: BrowserBridgeCommand) => void) | undefined
  const bridge = {
    setTabs: vi.fn(async () => {}),
    reply: vi.fn(async () => {}),
    onCommand: vi.fn((listener: typeof command) => { command = listener; return () => {} })
  }
  Object.defineProperty(window, 'dsGui', { configurable: true, value: { browserBridge: bridge } })
  const container = document.createElement('div'); document.body.append(container)
  const root = createRoot(container)
  return {
    bridge, container, root,
    send: async (requestId: string, value: BrowserBridgeCommand) => { await act(async () => command!(requestId, value)) },
    ready: async (webview: Element, id: number) => {
      await act(async () => {
        Object.assign(webview, { getWebContentsId: () => id, setAudioMuted: vi.fn() })
        webview.dispatchEvent(new Event('dom-ready'))
      })
    },
    close: async () => { await act(async () => root.unmount()); container.remove() }
  }
}

it('keeps every tab painted, showing only the displayed one under the panel', async () => {
  const h = mount()
  try {
    const first = openPageTab('one', 'http://localhost:5173/')
    openPageTab('two', 'https://example.test/')
    setPageDisplay({ browserId: 'one', rect: { top: 80, left: 600, width: 500, height: 400 } })
    await act(async () => h.root.render(createElement(BrowserPageLayer)))
    const pages = [...h.container.querySelectorAll<HTMLElement>('.ds-browser-page')]
    expect(pages.map(page => page.querySelector('webview')?.getAttribute('src')))
      .toEqual(['about:blank', 'http://localhost:5173/', 'about:blank', 'https://example.test/'])
    const shown = pages.filter(page => page.classList.contains('is-shown'))
    expect(shown).toHaveLength(1)
    expect(shown[0]!.style.top).toBe('80px')
    expect(shown[0]!.querySelector('webview')?.getAttribute('src')).toBe('http://localhost:5173/')
    // Hidden tabs keep the panel's size so their pages lay out and capture the same.
    expect(pages.find(page => !page.classList.contains('is-shown'))!.style.width).toBe('500px')
    expect(useBrowserPagesStore.getState().sessions.one!.activeTabId).toBe(first)
  } finally { await h.close() }
})

it("offers attached tabs to the bridge and follows the runtime's tab requests", async () => {
  const h = mount()
  try {
    await act(async () => h.root.render(createElement(BrowserPageLayer)))
    await h.send('open', { kind: 'open', browserId: 'one' })
    expect(h.bridge.reply).toHaveBeenLastCalledWith('open', { ok: true })
    const blank = h.container.querySelector('webview')!
    await h.ready(blank, 41)
    const [first] = useBrowserPagesStore.getState().sessions.one!.tabs
    expect(h.bridge.setTabs).toHaveBeenLastCalledWith('one', [{ tabId: first!.id, webContentsId: 41, inputBlocked: true, active: true, visible: false }])

    await h.send('retain', { kind: 'retain', browserId: 'one', retained: true })
    expect(useBrowserPagesStore.getState().sessions.one!.retained).toBe(true)
    await h.send('create', { kind: 'create', browserId: 'one', url: 'https://example.test/' })
    const created = useBrowserPagesStore.getState().sessions.one!
    expect(created.tabs).toHaveLength(2)
    expect(h.bridge.reply).toHaveBeenLastCalledWith('create', { ok: true, tabId: created.activeTabId })

    await h.send('activate', { kind: 'activate', browserId: 'one', tabId: first!.id })
    expect(useBrowserPagesStore.getState().sessions.one!.activeTabId).toBe(first!.id)
    await h.send('close', { kind: 'close', browserId: 'one', tabId: created.activeTabId })
    expect(useBrowserPagesStore.getState().sessions.one!.tabs.map(tab => tab.id)).toEqual([first!.id])
    await h.send('gone', { kind: 'activate', browserId: 'one', tabId: 'missing' })
    expect(h.bridge.reply).toHaveBeenLastCalledWith('gone', { ok: false, error: 'Tab no longer exists' })
  } finally { await h.close() }
})

it('replaces a closed last tab with a blank one so the runtime always has a page', async () => {
  const h = mount()
  try {
    await act(async () => h.root.render(createElement(BrowserPageLayer)))
    await h.send('open', { kind: 'open', browserId: 'one' })
    const [only] = useBrowserPagesStore.getState().sessions.one!.tabs
    await h.send('close', { kind: 'close', browserId: 'one', tabId: only!.id })
    const [replacement] = useBrowserPagesStore.getState().sessions.one!.tabs
    expect(replacement!.id).not.toBe(only!.id)
    expect(replacement!.url).toBe('about:blank')
  } finally { await h.close() }
})

it('keeps a tab quiet when it finishes loading out of sight', async () => {
  const h = mount()
  try {
    openPageTab('one', 'https://example.test/video')
    await act(async () => h.root.render(createElement(BrowserPageLayer)))
    const webview = [...h.container.querySelectorAll('webview')].at(-1)!
    const setAudioMuted = vi.fn()
    await act(async () => {
      Object.assign(webview, { getWebContentsId: () => 7, setAudioMuted })
      webview.dispatchEvent(new Event('dom-ready'))
    })
    expect(setAudioMuted).toHaveBeenCalledWith(true)
  } finally { await h.close() }
})

it('pauses media in a tab once it is no longer shown', async () => {
  const h = mount()
  try {
    openPageTab('one', 'https://example.test/video')
    setPageDisplay({ browserId: 'one', rect: { top: 0, left: 0, width: 400, height: 300 } })
    await act(async () => h.root.render(createElement(BrowserPageLayer)))
    const webview = h.container.querySelector('.ds-browser-page.is-shown webview')!
    const executeJavaScript = vi.fn(async () => undefined)
    await act(async () => {
      Object.assign(webview, { getWebContentsId: () => 9, setAudioMuted: vi.fn(), executeJavaScript })
      webview.dispatchEvent(new Event('dom-ready'))
    })
    expect(executeJavaScript).not.toHaveBeenCalled()
    await act(async () => setPageDisplay(null))
    expect(executeJavaScript).toHaveBeenCalledWith(expect.stringContaining('.pause()'))
  } finally { await h.close() }
})

it('shows where the shown page is scrolled, and nothing once the page fits', async () => {
  vi.useFakeTimers()
  const h = mount()
  try {
    openPageTab('one', 'https://example.test/long')
    setPageDisplay({ browserId: 'one', rect: { top: 0, left: 0, width: 400, height: 300 } })
    await act(async () => h.root.render(createElement(BrowserPageLayer)))
    const page = h.container.querySelector('.ds-browser-page.is-shown')!
    const webview = page.querySelector('webview')!
    let metrics: unknown = { y: [750, 500, 2000], x: null }
    const executeJavaScript = vi.fn(async (_code: string) => metrics)
    await act(async () => {
      Object.assign(webview, { getWebContentsId: () => 9, setAudioMuted: vi.fn(), executeJavaScript })
      webview.dispatchEvent(new Event('dom-ready'))
    })
    expect(page.querySelector('.ds-browser-scrollbar')).toBeNull()
    await act(async () => { await vi.advanceTimersByTimeAsync(150) })
    expect(() => new Function(executeJavaScript.mock.calls[0]![0])).not.toThrow()
    const thumb = page.querySelector<HTMLElement>('.ds-browser-scrollbar.is-vertical > span')!
    expect([thumb.style.top, thumb.style.height]).toEqual(['37.5%', '25%'])
    expect(page.querySelector('.ds-browser-scrollbar.is-horizontal')).toBeNull()
    metrics = { y: null, x: [0, 400, 1600] }
    await act(async () => { await vi.advanceTimersByTimeAsync(150) })
    const wide = page.querySelector<HTMLElement>('.ds-browser-scrollbar.is-horizontal > span')!
    expect([wide.style.left, wide.style.width]).toEqual(['0%', '25%'])
    expect(page.querySelector('.ds-browser-scrollbar.is-vertical')).toBeNull()
    metrics = null
    await act(async () => { await vi.advanceTimersByTimeAsync(150) })
    expect(page.querySelector('.ds-browser-scrollbar')).toBeNull()
  } finally { await h.close(); vi.useRealTimers() }
})


it('opens background links without replacing or activating the source page', async () => {
  const h = mount()
  try {
    const source = openPageTab('one', 'https://example.test/draft')
    await act(async () => h.root.render(createElement(BrowserPageLayer)))
    const webview = h.container.querySelector('webview[src="https://example.test/draft"]')
    await h.send('link', { kind: 'create', browserId: 'one', url: 'https://example.test/result', background: true })
    const session = useBrowserPagesStore.getState().sessions.one!
    expect(session.activeTabId).toBe(source)
    expect(session.tabs.at(-1)?.url).toBe('https://example.test/result')
    expect(h.bridge.reply).toHaveBeenLastCalledWith('link', { ok: true, tabId: session.tabs.at(-1)!.id })
    expect(h.container.querySelector('webview[src="https://example.test/draft"]')).toBe(webview)
  } finally { await h.close() }
})
