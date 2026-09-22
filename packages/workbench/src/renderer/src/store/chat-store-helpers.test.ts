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

// Runtime progress upserts can arrive while the following model reply streams.
import { completeAssistantProgress } from './chat-store'
import type { ProcessIntentMeta } from '../agent/types'

describe('completeAssistantProgress', () => {
  it('keeps an empty frame invisible and preserves the current stream when wording arrives', () => {
    const intent: ProcessIntentMeta = { scope: 'pre_tool', source: 'none' }
    const first = completeAssistantProgress({ blocks: [], liveAssistant: '新的正文正在输出' },
      'intent', undefined, '', intent)
    expect(first.liveAssistant).toBe('新的正文正在输出')
    expect(first.blocks[0]).toMatchObject({ id: 'intent', text: '' })
    const filled = completeAssistantProgress(first, 'intent', undefined, '已确认原因，接下来验证修复。',
      { ...intent, source: 'narration_service' })
    expect(filled.blocks).toHaveLength(1)
    expect(filled.blocks[0]).toMatchObject({ text: '已确认原因，接下来验证修复。' })
    expect(filled.liveAssistant).toBe('新的正文正在输出')
    const replay = completeAssistantProgress(filled, 'intent', undefined, '已确认原因，接下来验证修复。',
      { ...intent, source: 'narration_service' })
    expect(replay).toEqual(filled)
  })

  it('completes a primary preface once; its later metadata update preserves the next stream', () => {
    const first = completeAssistantProgress({ blocks: [], liveAssistant: '正在核对' }, 'primary', undefined, '正在核对')
    expect(first.liveAssistant).toBe('')
    const tagged = completeAssistantProgress({ ...first, liveAssistant: '下一轮内容' }, 'primary', undefined,
      '正在核对', { scope: 'pre_tool', source: 'primary_model' })
    expect(tagged.liveAssistant).toBe('下一轮内容')
    expect(tagged.blocks).toHaveLength(1)
  })
})
