import { describe, expect, it } from 'vitest'
import { decodeModelRef, encodeModelRef } from './model-ref'

describe('model refs', () => {
  it('keeps built-in DeepSeek ids backwards compatible', () => {
    expect(encodeModelRef('deepseek', 'deepseek-v4-pro')).toBe('deepseek-v4-pro')
    expect(decodeModelRef('deepseek-v4-pro')).toEqual({
      providerId: 'deepseek',
      modelId: 'deepseek-v4-pro'
    })
  })

  it('preserves provider ownership for duplicate custom model ids', () => {
    expect(decodeModelRef(encodeModelRef('qingyun', 'claude-sonnet'))).toEqual({
      providerId: 'qingyun',
      modelId: 'claude-sonnet'
    })
    expect(encodeModelRef('ark', 'claude-sonnet')).not.toBe(
      encodeModelRef('qingyun', 'claude-sonnet')
    )
  })
})
