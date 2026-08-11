import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  clampIdeChatRailWidth,
  IDE_CHAT_RAIL_DEFAULT_WIDTH,
  IDE_CHAT_RAIL_MAX_WIDTH,
  IDE_CHAT_RAIL_MIN_WIDTH,
  nextIdeActivitySelection,
  persistIdeCenterTab,
  persistLayoutMode,
  readStoredIdeCenterTab,
  readStoredLayoutMode
} from './workbench-layout-mode'

function installMemoryStorage(): void {
  const map = new Map<string, string>()
  const fakeStorage = {
    getItem: (key: string) => map.get(key) ?? null,
    setItem: (key: string, value: string) => {
      map.set(key, String(value))
    },
    removeItem: (key: string) => {
      map.delete(key)
    },
    clear: () => {
      map.clear()
    },
    key: (index: number) => [...map.keys()][index] ?? null,
    get length() {
      return map.size
    }
  }
  vi.stubGlobal('localStorage', fakeStorage)
  vi.stubGlobal('window', { localStorage: fakeStorage })
}

beforeEach(() => {
  installMemoryStorage()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('workbench-layout-mode', () => {
  it('defaults layout mode to chat', () => {
    expect(readStoredLayoutMode()).toBe('chat')
  })

  it('persists and restores ide layout mode', () => {
    persistLayoutMode('ide')
    expect(readStoredLayoutMode()).toBe('ide')
  })

  it('persists ide center tab', () => {
    persistIdeCenterTab('search')
    expect(readStoredIdeCenterTab()).toBe('search')
  })

  it('clamps chat rail width', () => {
    expect(clampIdeChatRailWidth(10)).toBe(IDE_CHAT_RAIL_MIN_WIDTH)
    expect(clampIdeChatRailWidth(10_000)).toBe(IDE_CHAT_RAIL_MAX_WIDTH)
    expect(clampIdeChatRailWidth(IDE_CHAT_RAIL_DEFAULT_WIDTH)).toBe(IDE_CHAT_RAIL_DEFAULT_WIDTH)
  })

  it('toggles activity sidebar like VS Code', () => {
    expect(nextIdeActivitySelection('files', true, 'files')).toEqual({
      tab: 'files',
      sidebarVisible: false
    })
    expect(nextIdeActivitySelection('files', false, 'files')).toEqual({
      tab: 'files',
      sidebarVisible: true
    })
    expect(nextIdeActivitySelection('files', true, 'search')).toEqual({
      tab: 'search',
      sidebarVisible: true
    })
  })
})
