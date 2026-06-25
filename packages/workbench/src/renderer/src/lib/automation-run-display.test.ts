import { describe, expect, it } from 'vitest'
import type { AutomationRecord, AutomationRunRecord } from './automation-runtime-client'
import { formatRunDeliveryStatus } from './automation-run-display'

const t = (key: string) => key

const automationWithFeishu: AutomationRecord = {
  id: 'a1',
  name: 'Task',
  prompt: 'p',
  rrule: 'FREQ=HOURLY',
  status: 'active',
  delivery: { mode: 'feishu', to: 'ou_x' }
}

describe('automation-run-display', () => {
  it('shows not configured when automation has no delivery', () => {
    const run: AutomationRunRecord = {
      id: 'r1',
      automation_id: 'a1',
      scheduled_for: '2026-01-01T00:00:00Z',
      status: 'completed',
      created_at: '2026-01-01T00:00:00Z',
      delivery_done: false
    }
    expect(formatRunDeliveryStatus(run, { ...automationWithFeishu, delivery: {} }, t)).toBe(
      'automationRunDeliveryNotConfigured'
    )
  })

  it('shows delivery failed when run error mentions delivery', () => {
    const run: AutomationRunRecord = {
      id: 'r1',
      automation_id: 'a1',
      scheduled_for: '2026-01-01T00:00:00Z',
      status: 'completed',
      created_at: '2026-01-01T00:00:00Z',
      delivery_done: false,
      error: 'delivery failed: smtp timeout'
    }
    expect(formatRunDeliveryStatus(run, automationWithFeishu, t)).toBe(
      'automationRunDeliveryFailed'
    )
  })

  it('shows delivered when delivery_done is true', () => {
    const run: AutomationRunRecord = {
      id: 'r1',
      automation_id: 'a1',
      scheduled_for: '2026-01-01T00:00:00Z',
      status: 'completed',
      created_at: '2026-01-01T00:00:00Z',
      delivery_done: true
    }
    expect(formatRunDeliveryStatus(run, automationWithFeishu, t)).toBe('automationRunDelivered')
  })
})
