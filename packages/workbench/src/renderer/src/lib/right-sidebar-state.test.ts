// @vitest-environment happy-dom
import { beforeEach, expect, it } from 'vitest'
import {
  addRightSidebarTab, removeRightSidebarTab, readStoredRightSidebarPanels,
  persistRightSidebarPanels, type RightSidebarPanels
} from './right-sidebar-state'

beforeEach(() => {
  const values = new Map<string, string>()
  Object.defineProperty(window, 'localStorage', { configurable: true, value: {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value)
  } })
})

it('starts empty even with the old fixed-tab preference', () => {
  window.localStorage.setItem('deepseekgui.layout.rightSidebarTab', 'editor')
  expect(readStoredRightSidebarPanels()).toEqual({ tabs: [], activeTab: null })
})

it('adds, activates without duplicates, and closes to a neighbor or launcher', () => {
  let state: RightSidebarPanels = { tabs: [], activeTab: null }
  state = addRightSidebarTab(state, 'terminal')
  state = addRightSidebarTab(state, 'editor')
  state = addRightSidebarTab(state, 'terminal')
  expect(state).toEqual({ tabs: ['terminal', 'editor'], activeTab: 'terminal' })
  expect(removeRightSidebarTab(state, 'editor')).toEqual({ tabs: ['terminal'], activeTab: 'terminal' })
  state = removeRightSidebarTab(state, 'terminal')
  expect(state).toEqual({ tabs: ['editor'], activeTab: 'editor' })
  expect(removeRightSidebarTab(state, 'editor')).toEqual({ tabs: [], activeTab: null })
  expect(removeRightSidebarTab(state, 'runs')).toBe(state)
})

it('restores panels but excludes transient runs and invalid saved tabs', () => {
  persistRightSidebarPanels({ tabs: ['terminal', 'preview', 'runs'], activeTab: 'runs' })
  expect(readStoredRightSidebarPanels()).toEqual({ tabs: ['terminal', 'preview'], activeTab: 'terminal' })
  window.localStorage.setItem('deepseekgui.layout.rightSidebarPanels', JSON.stringify({ tabs: ['editor', 'unknown', 'editor'], activeTab: 'unknown' }))
  expect(readStoredRightSidebarPanels()).toEqual({ tabs: ['editor'], activeTab: 'editor' })
  window.localStorage.setItem('deepseekgui.layout.rightSidebarPanels', '{')
  expect(readStoredRightSidebarPanels()).toEqual({ tabs: [], activeTab: null })
})
