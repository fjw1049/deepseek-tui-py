import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mergeComposerPickList, readStoredComposerModel } from './chat-store-helpers'

const STORAGE_KEY = 'deepseekgui.composerModel'

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

describe('mergeComposerPickList', () => {
  it('does not inject default DeepSeek ids when none are configured', () => {
    expect(mergeComposerPickList(false, [])).toEqual([])
    expect(mergeComposerPickList(true, [])).toEqual([])
    expect(mergeComposerPickList(true, ['kimi/kimi-k3'])).toEqual(['kimi/kimi-k3'])
  })

  it('pins default DeepSeek ids only when they are actually present', () => {
    expect(
      mergeComposerPickList(true, ['glm/glm-4', 'deepseek-v4-flash', 'deepseek-v4-pro'])
    ).toEqual(['deepseek-v4-pro', 'deepseek-v4-flash', 'glm/glm-4'])
  })
})

describe('readStoredComposerModel', () => {
  it('falls back to the first allowed model instead of a missing DeepSeek default', () => {
    localStorage.setItem(STORAGE_KEY, 'deepseek-v4-pro')
    expect(readStoredComposerModel(['kimi/kimi-k3'])).toBe('kimi/kimi-k3')
  })

  it('returns empty when no models are configured', () => {
    localStorage.setItem(STORAGE_KEY, 'deepseek-v4-pro')
    expect(readStoredComposerModel([])).toBe('')
  })
})
