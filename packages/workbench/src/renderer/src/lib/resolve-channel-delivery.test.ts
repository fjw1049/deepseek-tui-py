import { describe, expect, it } from 'vitest'
import {
  resolveDefaultDeliveryFromChannels,
  templateDeliveryCardHint,
  type ChannelDeliveryState
} from './resolve-channel-delivery'

const t = (key: string) => key

describe('resolve-channel-delivery', () => {
  it('prefers feishu when both channels are ready', () => {
    const state: ChannelDeliveryState = {
      feishuDefault: 'ou_abc',
      emailDefault: 'me@example.com',
      feishuChannelReady: true,
      wecomChannelReady: true,
      emailChannelReady: true
    }
    expect(resolveDefaultDeliveryFromChannels(state)).toEqual({
      mode: 'feishu',
      to: 'ou_abc',
      best_effort: false
    })
  })

  it('uses wecom when feishu is not ready', () => {
    const state: ChannelDeliveryState = {
      feishuDefault: '',
      emailDefault: 'me@example.com',
      feishuChannelReady: false,
      wecomChannelReady: true,
      emailChannelReady: true
    }
    expect(resolveDefaultDeliveryFromChannels(state)).toEqual({
      mode: 'wecom',
      best_effort: false
    })
    expect(templateDeliveryCardHint(state, t)).toBe('automationTemplateDeliveryWecom')
  })

  it('falls back to email when feishu and wecom are not ready', () => {
    const state: ChannelDeliveryState = {
      feishuDefault: '',
      emailDefault: 'me@example.com',
      feishuChannelReady: false,
      wecomChannelReady: false,
      emailChannelReady: true
    }
    expect(resolveDefaultDeliveryFromChannels(state)).toEqual({
      mode: 'email',
      to: 'me@example.com',
      best_effort: false
    })
  })

  it('returns undefined when no channel is ready', () => {
    const state: ChannelDeliveryState = {
      feishuDefault: '',
      emailDefault: '',
      feishuChannelReady: false,
      wecomChannelReady: false,
      emailChannelReady: false
    }
    expect(resolveDefaultDeliveryFromChannels(state)).toBeUndefined()
    expect(templateDeliveryCardHint(state, t)).toBe('automationTemplateDeliveryUnset')
  })
})
