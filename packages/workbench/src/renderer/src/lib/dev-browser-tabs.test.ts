import { describe, expect, it } from 'vitest'
import {
  createTab,
  formatAddressInput,
  reduceCloseTab,
  reduceOpenOrFocusUrl,
  resolveAutoFollow,
  selectDevBrowserView,
  updateTabById,
  type PreviewTab,
  type TabState
} from './dev-browser-tabs'

function tab(id: string, url: string | null = null, title = ''): PreviewTab {
  return { id, url, title }
}

function state(tabs: PreviewTab[], activeTabId: string): TabState {
  return { tabs, activeTabId }
}

describe('resolveAutoFollow', () => {
  it('defaults to off when nothing is stored', () => {
    expect(resolveAutoFollow(null)).toBe(false)
  })

  it('only enables for an explicit "true"', () => {
    expect(resolveAutoFollow('true')).toBe(true)
    expect(resolveAutoFollow('false')).toBe(false)
    expect(resolveAutoFollow('1')).toBe(false)
    expect(resolveAutoFollow('')).toBe(false)
  })
})

describe('reduceOpenOrFocusUrl', () => {
  it('fills the initial blank tab instead of appending', () => {
    const initial = state([tab('a')], 'a')
    const next = reduceOpenOrFocusUrl(initial, 'http://127.0.0.1:5173/')
    expect(next.tabs).toHaveLength(1)
    expect(next.tabs[0]).toMatchObject({ id: 'a', url: 'http://127.0.0.1:5173/', title: '' })
    expect(next.activeTabId).toBe('a')
  })

  it('focuses an existing tab with the same URL instead of duplicating', () => {
    const initial = state(
      [tab('a', 'http://127.0.0.1:5173/'), tab('b', 'https://example.com/')],
      'a'
    )
    const next = reduceOpenOrFocusUrl(initial, 'https://example.com/')
    expect(next.tabs).toBe(initial.tabs)
    expect(next.activeTabId).toBe('b')
  })

  it('keeps the active tab when select is false', () => {
    const initial = state([tab('a', 'http://127.0.0.1:5173/'), tab('b')], 'a')
    const next = reduceOpenOrFocusUrl(initial, 'https://example.com/', { select: false })
    expect(next.activeTabId).toBe('a')
    expect(next.tabs.find((t) => t.url === 'https://example.com/')).toBeTruthy()
  })

  it('appends a new tab when no blank or matching tab exists', () => {
    const initial = state([tab('a', 'http://127.0.0.1:5173/')], 'a')
    const next = reduceOpenOrFocusUrl(initial, 'https://example.com/', { title: 'Example' })
    expect(next.tabs).toHaveLength(2)
    expect(next.tabs[1]).toMatchObject({ url: 'https://example.com/', title: 'Example' })
    expect(next.activeTabId).toBe(next.tabs[1]!.id)
  })

  it('updates the title when refocusing an existing tab', () => {
    const initial = state([tab('a', 'https://example.com/')], 'a')
    const next = reduceOpenOrFocusUrl(initial, 'https://example.com/', { title: 'New title' })
    expect(next.tabs[0]!.title).toBe('New title')
  })
})

describe('reduceCloseTab', () => {
  it('clears the sole tab in place instead of removing it', () => {
    const initial = state([tab('a', 'https://example.com/', 'Example')], 'a')
    const next = reduceCloseTab(initial, 'a')
    expect(next.clearedSoleTab).toBe(true)
    expect(next.tabs).toHaveLength(1)
    expect(next.tabs[0]).toMatchObject({ id: 'a', url: null, title: '' })
    expect(next.activeTabId).toBe('a')
  })

  it('is a no-op on an already blank sole tab', () => {
    const initial = state([tab('a')], 'a')
    const next = reduceCloseTab(initial, 'a')
    expect(next.clearedSoleTab).toBe(false)
    expect(next.tabs).toBe(initial.tabs)
  })

  it('focuses the left neighbor when closing the active tab', () => {
    const initial = state([tab('a'), tab('b'), tab('c')], 'c')
    const next = reduceCloseTab(initial, 'c')
    expect(next.tabs.map((t) => t.id)).toEqual(['a', 'b'])
    expect(next.activeTabId).toBe('b')
  })

  it('falls back to the first tab when closing the leftmost active tab', () => {
    const initial = state([tab('a'), tab('b')], 'a')
    const next = reduceCloseTab(initial, 'a')
    expect(next.activeTabId).toBe('b')
  })

  it('keeps the active tab when closing an inactive tab', () => {
    const initial = state([tab('a'), tab('b'), tab('c')], 'b')
    const next = reduceCloseTab(initial, 'c')
    expect(next.tabs.map((t) => t.id)).toEqual(['a', 'b'])
    expect(next.activeTabId).toBe('b')
  })

  it('ignores unknown tab ids', () => {
    const initial = state([tab('a')], 'a')
    const next = reduceCloseTab(initial, 'missing')
    expect(next.tabs).toBe(initial.tabs)
    expect(next.activeTabId).toBe('a')
  })
})

describe('updateTabById', () => {
  it('patches only the matching tab', () => {
    const tabs = [tab('a', 'https://a.example/'), tab('b', 'https://b.example/')]
    const next = updateTabById(tabs, 'b', { title: 'B' })
    expect(next[0]).toBe(tabs[0])
    expect(next[1]).toMatchObject({ id: 'b', title: 'B', url: 'https://b.example/' })
  })

  it('returns the same array reference when the patch changes nothing', () => {
    // Webview events re-report the same URL/title constantly; a no-op patch
    // must not create a new array or it re-renders (and re-runs effects)
    // on every event.
    const tabs = [tab('a', 'https://a.example/', 'A')]
    expect(updateTabById(tabs, 'a', { url: 'https://a.example/' })).toBe(tabs)
    expect(updateTabById(tabs, 'a', { title: 'A' })).toBe(tabs)
    expect(updateTabById(tabs, 'missing', { title: 'X' })).toBe(tabs)
  })
})

describe('selectDevBrowserView', () => {
  it('renders the empty state without an active URL', () => {
    expect(selectDevBrowserView(null, true)).toBe('empty')
    expect(selectDevBrowserView(null, false)).toBe('empty')
  })

  it('uses the Electron webview whenever available', () => {
    expect(selectDevBrowserView('https://example.com/', true)).toBe('webview')
    expect(selectDevBrowserView('http://127.0.0.1:5173/', true)).toBe('webview')
  })

  it('falls back to iframe for local previews and unsupported for public sites', () => {
    expect(selectDevBrowserView('http://127.0.0.1:5173/', false)).toBe('iframe')
    expect(selectDevBrowserView('http://192.168.1.10:3000/', false)).toBe('iframe')
    expect(selectDevBrowserView('https://example.com/', false)).toBe('unsupported')
  })
})

describe('formatAddressInput', () => {
  it('strips scheme and root slash for display', () => {
    expect(formatAddressInput('https://example.com/')).toBe('example.com')
    expect(formatAddressInput('http://127.0.0.1:5173/docs?q=1#top')).toBe(
      '127.0.0.1:5173/docs?q=1#top'
    )
    expect(formatAddressInput(null)).toBe('')
  })
})

describe('createTab', () => {
  it('generates unique ids', () => {
    expect(createTab().id).not.toBe(createTab().id)
  })
})
