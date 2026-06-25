import { describe, expect, it } from 'vitest'
import {
  applyEmailProviderPreset,
  inferEmailProviderFromHost
} from './email-channel'

describe('inferEmailProviderFromHost', () => {
  it('detects common providers', () => {
    expect(inferEmailProviderFromHost('smtp.163.com')).toBe('163')
    expect(inferEmailProviderFromHost('smtp.qq.com')).toBe('qq')
    expect(inferEmailProviderFromHost('smtp.gmail.com')).toBe('gmail')
    expect(inferEmailProviderFromHost('smtp.office365.com')).toBe('outlook')
    expect(inferEmailProviderFromHost('mail.example.com')).toBe('custom')
  })
})

describe('applyEmailProviderPreset', () => {
  it('returns 163 defaults', () => {
    expect(applyEmailProviderPreset('163')).toEqual({
      smtpHost: 'smtp.163.com',
      smtpPort: '465',
      smtpSsl: true,
      smtpStarttls: false
    })
  })

  it('returns null for custom', () => {
    expect(applyEmailProviderPreset('custom')).toBeNull()
  })
})
