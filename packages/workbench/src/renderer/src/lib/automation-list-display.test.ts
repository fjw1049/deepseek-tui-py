import { describe, expect, it } from 'vitest'
import {
  automationCardPreview,
  automationDeliveryCardHint,
  automationDeliveryDetail
} from './automation-list-display'

describe('automation list display', () => {
  it('flattens multiline prompt for card preview', () => {
    expect(automationCardPreview('line one\nline two\n\nignored block')).toBe('line one line two')
  })

  it('hides opaque delivery ids on cards', () => {
    const row = {
      id: '1',
      name: 't',
      prompt: '',
      rrule: '',
      status: 'active',
      delivery: { mode: 'feishu', to: 'oc_5b08c88b758c17b6dffd3a53bf501a36' }
    }
    const t = (key: string) => {
      if (key === 'automationDeliveryFeishuBound') return '飞书 · 已绑定'
      return key
    }
    expect(automationDeliveryCardHint(row, t)).toBe('飞书 · 已绑定')
    expect(automationDeliveryDetail(row, t)).toBe('飞书 · 已绑定')
  })

  it('shows unset delivery on cards', () => {
    const row = {
      id: '1',
      name: 't',
      prompt: '',
      rrule: '',
      status: 'active',
      delivery: {}
    }
    const t = (key: string) => (key === 'automationDeliveryUnsetShort' ? '未设置投递' : key)
    expect(automationDeliveryCardHint(row, t)).toBe('未设置投递')
  })

  it('shows email targets on cards', () => {
    const row = {
      id: '1',
      name: 't',
      prompt: '',
      rrule: '',
      status: 'active',
      delivery: { mode: 'email', to: 'me@example.com' }
    }
    const t = (key: string) => (key === 'automationDeliveryEmailShort' ? '邮箱' : key)
    expect(automationDeliveryCardHint(row, t)).toBe('邮箱 · me@example.com')
  })
})
