import { describe, expect, it } from 'vitest'
import {
  buildWecomWebhookUrl,
  isWecomWebhookConfigured,
  parseWecomWebhookKey,
  WECOM_WEBHOOK_BASE
} from './wecom-channel'

const SAMPLE_KEY = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
const SAMPLE_URL = `${WECOM_WEBHOOK_BASE}?key=${SAMPLE_KEY}`

describe('wecom-channel', () => {
  it('parses bare webhook key', () => {
    expect(parseWecomWebhookKey(SAMPLE_KEY)).toBe(SAMPLE_KEY)
  })

  it('parses full webhook URL', () => {
    expect(parseWecomWebhookKey(SAMPLE_URL)).toBe(SAMPLE_KEY)
  })

  it('rejects invalid input', () => {
    expect(parseWecomWebhookKey('')).toBeNull()
    expect(parseWecomWebhookKey('not-a-url')).toBeNull()
    expect(parseWecomWebhookKey('https://example.com/webhook/send?key=x')).toBeNull()
  })

  it('builds webhook URL from key', () => {
    expect(buildWecomWebhookUrl(SAMPLE_KEY)).toBe(SAMPLE_URL)
  })

  it('detects configured state', () => {
    expect(isWecomWebhookConfigured(SAMPLE_KEY)).toBe(true)
    expect(isWecomWebhookConfigured(SAMPLE_URL)).toBe(true)
    expect(isWecomWebhookConfigured('')).toBe(false)
  })
})
