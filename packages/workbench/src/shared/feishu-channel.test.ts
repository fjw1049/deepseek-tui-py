import { describe, expect, it } from 'vitest'
import { feishuReceiveIdType } from './feishu-channel'

describe('feishuReceiveIdType', () => {
  it('maps Feishu id prefixes like the Python runtime', () => {
    expect(feishuReceiveIdType('oc_abc')).toBe('chat_id')
    expect(feishuReceiveIdType('ou_abc')).toBe('open_id')
    expect(feishuReceiveIdType('on_abc')).toBe('union_id')
    expect(feishuReceiveIdType('unknown')).toBe('open_id')
  })
})
