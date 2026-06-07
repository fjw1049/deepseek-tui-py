import { describe, expect, it } from 'vitest'
import { upsertTomlSections } from '@shared/toml-section'
import {
  EMPTY_EMAIL_CONFIG,
  isEmailConfigured,
  parseEmailConfig
} from './resolve-automation-email-config'

const FULL_CONFIG = `
[automation]
mail_to = "alice@corp.com"

[automation.email]
smtp_host = "smtp.corp.com"
smtp_port = 465
smtp_starttls = false
username = "alice@corp.com"
from_addr = "bot@corp.com"
password_env = "CORP_SMTP_PASS"
`.trim()

const MINIMAL_CONFIG = `
[automation]
mail_to = "bob@example.com"

[automation.email]
smtp_host = "smtp.example.com"
username = "bob@example.com"
`.trim()

describe('parseEmailConfig', () => {
  it('parses a fully populated config.toml', () => {
    const cfg = parseEmailConfig(FULL_CONFIG)
    expect(cfg).toEqual({
      mailTo: 'alice@corp.com',
      smtpHost: 'smtp.corp.com',
      smtpPort: '465',
      smtpStarttls: 'false',
      username: 'alice@corp.com',
      fromAddr: 'bot@corp.com',
      passwordEnv: 'CORP_SMTP_PASS'
    })
  })

  it('fills defaults for missing optional fields', () => {
    const cfg = parseEmailConfig(MINIMAL_CONFIG)
    expect(cfg.mailTo).toBe('bob@example.com')
    expect(cfg.smtpHost).toBe('smtp.example.com')
    expect(cfg.username).toBe('bob@example.com')
    expect(cfg.smtpPort).toBe('587')
    expect(cfg.smtpStarttls).toBe('true')
    expect(cfg.fromAddr).toBe('')
    expect(cfg.passwordEnv).toBe('DEEPSEEK_EMAIL_PASSWORD')
  })

  it('returns all defaults for empty content', () => {
    expect(parseEmailConfig('')).toEqual(EMPTY_EMAIL_CONFIG)
  })

  it('reads unquoted boolean and numeric values', () => {
    const toml = `
[automation.email]
smtp_port = 25
smtp_starttls = true
`.trim()
    const cfg = parseEmailConfig(toml)
    expect(cfg.smtpPort).toBe('25')
    expect(cfg.smtpStarttls).toBe('true')
  })

  it('ignores keys from wrong sections', () => {
    const toml = `
[other]
mail_to = "wrong@nope.com"
smtp_host = "wrong.host"

[automation]
mail_to = "correct@yes.com"
`.trim()
    const cfg = parseEmailConfig(toml)
    expect(cfg.mailTo).toBe('correct@yes.com')
    expect(cfg.smtpHost).toBe('')
  })
})

describe('isEmailConfigured', () => {
  it('returns true when mailTo + smtpHost + username are set', () => {
    expect(
      isEmailConfigured({
        ...EMPTY_EMAIL_CONFIG,
        mailTo: 'a@b.com',
        smtpHost: 'smtp.b.com',
        username: 'a@b.com'
      })
    ).toBe(true)
  })

  it('returns false if any required field is empty', () => {
    expect(isEmailConfigured(EMPTY_EMAIL_CONFIG)).toBe(false)
    expect(
      isEmailConfigured({ ...EMPTY_EMAIL_CONFIG, mailTo: 'a@b.com', smtpHost: 'smtp.b.com' })
    ).toBe(false)
    expect(
      isEmailConfigured({ ...EMPTY_EMAIL_CONFIG, mailTo: 'a@b.com', username: 'a@b.com' })
    ).toBe(false)
  })
})

describe('round-trip: parse → upsert → re-parse', () => {
  it('preserves values through a write-then-read cycle', () => {
    const original = parseEmailConfig(FULL_CONFIG)

    const updated = upsertTomlSections(FULL_CONFIG, {
      automation: { mail_to: 'new@corp.com' },
      'automation.email': {
        smtp_host: 'smtp2.corp.com',
        smtp_port: 587,
        smtp_starttls: true,
        username: 'new@corp.com',
        from_addr: 'noreply@corp.com',
        password_env: 'NEW_PASS'
      }
    })

    const reparsed = parseEmailConfig(updated)
    expect(reparsed.mailTo).toBe('new@corp.com')
    expect(reparsed.smtpHost).toBe('smtp2.corp.com')
    expect(reparsed.smtpPort).toBe('587')
    expect(reparsed.smtpStarttls).toBe('true')
    expect(reparsed.username).toBe('new@corp.com')
    expect(reparsed.fromAddr).toBe('noreply@corp.com')
    expect(reparsed.passwordEnv).toBe('NEW_PASS')

    expect(reparsed.mailTo).not.toBe(original.mailTo)
  })

  it('creates sections from scratch when config is empty', () => {
    const updated = upsertTomlSections('', {
      automation: { mail_to: 'fresh@test.com' },
      'automation.email': {
        smtp_host: 'smtp.test.com',
        smtp_port: 587,
        smtp_starttls: true,
        username: 'fresh@test.com',
        from_addr: 'bot@test.com',
        password_env: 'TEST_PASS'
      }
    })

    const cfg = parseEmailConfig(updated)
    expect(cfg.mailTo).toBe('fresh@test.com')
    expect(cfg.smtpHost).toBe('smtp.test.com')
    expect(cfg.smtpPort).toBe('587')
    expect(cfg.username).toBe('fresh@test.com')
    expect(isEmailConfigured(cfg)).toBe(true)
  })
})
