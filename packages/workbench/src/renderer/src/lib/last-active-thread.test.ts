import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  LAST_ACTIVE_THREAD_STORAGE_KEY,
  readLastActiveThreadId,
  writeLastActiveThreadId
} from './last-active-thread'

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

describe('last-active-thread', () => {
  it('round-trips a thread id', () => {
    writeLastActiveThreadId('thr_abc')
    expect(readLastActiveThreadId()).toBe('thr_abc')
    expect(window.localStorage.getItem(LAST_ACTIVE_THREAD_STORAGE_KEY)).toBe('thr_abc')
  })

  it('clears storage when written null', () => {
    writeLastActiveThreadId('thr_abc')
    writeLastActiveThreadId(null)
    expect(readLastActiveThreadId()).toBeNull()
    expect(window.localStorage.getItem(LAST_ACTIVE_THREAD_STORAGE_KEY)).toBeNull()
  })

  it('trims whitespace and treats blank as null', () => {
    window.localStorage.setItem(LAST_ACTIVE_THREAD_STORAGE_KEY, '  thr_x  ')
    expect(readLastActiveThreadId()).toBe('thr_x')
    window.localStorage.setItem(LAST_ACTIVE_THREAD_STORAGE_KEY, '   ')
    expect(readLastActiveThreadId()).toBeNull()
  })
})
