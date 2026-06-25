/** Read/parse email SMTP config from config.toml `[automation]` + `[automation.email]`. */

import { readTomlString } from '@shared/toml-section'
import {
  applyEmailProviderPreset,
  DEFAULT_EMAIL_PASSWORD_ENV,
  inferEmailProviderFromHost,
  type EmailProviderId
} from '@shared/email-channel'

export type EmailChannelConfig = {
  provider: EmailProviderId
  mailTo: string
  smtpHost: string
  smtpPort: string
  smtpSsl: string
  smtpStarttls: string
  username: string
  fromAddr: string
  passwordEnv: string
}

export const EMPTY_EMAIL_CONFIG: EmailChannelConfig = {
  provider: 'custom',
  mailTo: '',
  smtpHost: '',
  smtpPort: '587',
  smtpSsl: 'false',
  smtpStarttls: 'true',
  username: '',
  fromAddr: '',
  passwordEnv: DEFAULT_EMAIL_PASSWORD_ENV
}

/** Like readTomlString but also handles unquoted values (numbers, booleans). */
function readTomlRaw(content: string, key: string, section: string): string | null {
  const quoted = readTomlString(content, key, { section })
  if (quoted !== null) return quoted
  const lines = content.split(/\r?\n/)
  let inSection = false
  for (const line of lines) {
    const sec = line.match(/^\s*\[([^\]]+)\]\s*$/)
    if (sec) {
      inSection = sec[1].trim() === section
      continue
    }
    if (!inSection) continue
    const m = line.match(new RegExp(`^\\s*${key}\\s*=\\s*([^#\\s]+)`))
    if (m) return m[1]?.trim() ?? ''
  }
  return null
}

export function parseEmailConfig(content: string): EmailChannelConfig {
  const smtpHost = readTomlRaw(content, 'smtp_host', 'automation.email') ?? ''
  return {
    provider: inferEmailProviderFromHost(smtpHost),
    mailTo: readTomlString(content, 'mail_to', { section: 'automation' }) ?? '',
    smtpHost,
    smtpPort: readTomlRaw(content, 'smtp_port', 'automation.email') ?? '587',
    smtpSsl: readTomlRaw(content, 'smtp_ssl', 'automation.email') ?? 'false',
    smtpStarttls: readTomlRaw(content, 'smtp_starttls', 'automation.email') ?? 'true',
    username: readTomlRaw(content, 'username', 'automation.email') ?? '',
    fromAddr: readTomlRaw(content, 'from_addr', 'automation.email') ?? '',
    passwordEnv: readTomlRaw(content, 'password_env', 'automation.email') ?? DEFAULT_EMAIL_PASSWORD_ENV
  }
}

export function isEmailConfigured(
  config: EmailChannelConfig,
  options?: { passwordConfigured?: boolean }
): boolean {
  const passwordConfigured = options?.passwordConfigured ?? false
  return Boolean(config.mailTo && config.smtpHost && config.username && passwordConfigured)
}

const PRESET_PROVIDER_IDS = ['163', 'qq', 'gmail', 'outlook'] as const satisfies readonly EmailProviderId[]

/** Resolve preset provider for the simplified channel UI (defaults to 163). */
export function resolveSimpleEmailProvider(
  config: EmailChannelConfig
): Exclude<EmailProviderId, 'custom'> {
  if (PRESET_PROVIDER_IDS.includes(config.provider as (typeof PRESET_PROVIDER_IDS)[number])) {
    return config.provider as Exclude<EmailProviderId, 'custom'>
  }
  const inferred = inferEmailProviderFromHost(config.smtpHost)
  if (inferred !== 'custom') return inferred
  return '163'
}

/** Apply mailbox preset SMTP fields and align username/from with mail_to when possible. */
export function normalizePresetEmailConfig(config: EmailChannelConfig): EmailChannelConfig {
  const provider = resolveSimpleEmailProvider(config)
  const preset = applyEmailProviderPreset(provider)
  if (!preset) return config

  const mailTo = config.mailTo.trim()
  const useMailAsIdentity = mailTo.includes('@')

  return {
    ...config,
    provider,
    smtpHost: preset.smtpHost,
    smtpPort: preset.smtpPort,
    smtpSsl: preset.smtpSsl ? 'true' : 'false',
    smtpStarttls: preset.smtpStarttls ? 'true' : 'false',
    username: useMailAsIdentity ? mailTo : config.username.trim(),
    fromAddr: useMailAsIdentity ? mailTo : config.fromAddr.trim() || config.username.trim()
  }
}
