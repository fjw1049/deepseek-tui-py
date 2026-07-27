import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  CHATS_ORDER_STORAGE_KEY,
  PROJECT_ORDER_STORAGE_KEY,
  PROJECT_THREAD_ORDERS_STORAGE_KEY,
  applyManualOrder,
  hasManualProjectOrder,
  loadChatsOrder,
  loadProjectOrder,
  loadProjectThreadOrder,
  moveIdBefore,
  persistChatsOrder,
  persistProjectOrder,
  persistProjectThreadOrder
} from './sidebar-manual-order'

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

describe('applyManualOrder', () => {
  it('returns current order when manual is empty', () => {
    expect(applyManualOrder(['a', 'b', 'c'], [])).toEqual(['a', 'b', 'c'])
    expect(applyManualOrder(['a', 'b'], null)).toEqual(['a', 'b'])
  })

  it('keeps manual prefix and appends unknown ids in current order', () => {
    expect(applyManualOrder(['a', 'b', 'c', 'd'], ['c', 'a'])).toEqual(['c', 'a', 'b', 'd'])
  })

  it('drops stale manual ids that are no longer current', () => {
    expect(applyManualOrder(['a', 'b'], ['x', 'b', 'a'])).toEqual(['b', 'a'])
  })
})

describe('moveIdBefore', () => {
  it('moves active id to over index', () => {
    expect(moveIdBefore(['a', 'b', 'c', 'd'], 'd', 'b')).toEqual(['a', 'd', 'b', 'c'])
    expect(moveIdBefore(['a', 'b', 'c'], 'a', 'c')).toEqual(['b', 'c', 'a'])
  })

  it('no-ops when ids missing or identical', () => {
    expect(moveIdBefore(['a', 'b'], 'a', 'a')).toEqual(['a', 'b'])
    expect(moveIdBefore(['a', 'b'], 'z', 'a')).toEqual(['a', 'b'])
  })
})

describe('persistence', () => {
  it('round-trips chats and project orders', () => {
    persistChatsOrder(['t1', 't2'])
    expect(loadChatsOrder()).toEqual(['t1', 't2'])

    persistProjectOrder(['/a', '/b'])
    expect(loadProjectOrder()).toEqual(['/a', '/b'])
    expect(hasManualProjectOrder()).toBe(true)

    persistProjectOrder([])
    expect(loadProjectOrder()).toEqual([])
    expect(hasManualProjectOrder()).toBe(false)

    // keys cleaned
    expect(window.localStorage.getItem(CHATS_ORDER_STORAGE_KEY)).toBeTruthy()
    expect(window.localStorage.getItem(PROJECT_ORDER_STORAGE_KEY)).toBeNull()
    expect(window.localStorage.getItem(PROJECT_THREAD_ORDERS_STORAGE_KEY)).toBeNull()
  })

  it('stores per-project thread orders', () => {
    persistProjectThreadOrder('/proj', ['t2', 't1'])
    expect(loadProjectThreadOrder('/proj')).toEqual(['t2', 't1'])
    persistProjectThreadOrder('/proj', [])
    expect(loadProjectThreadOrder('/proj')).toEqual([])
  })
})
