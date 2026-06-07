/** Read/parse email SMTP config from config.toml `[automation]` + `[automation.email]`. */

import { readTomlString } from '@shared/toml-section'

export type EmailChannelConfig = {
  mailTo: string
  smtpHost: string
  smtpPort: string
  smtpStarttls: string
  username: string
  fromAddr: string
  passwordEnv: string
}

export const EMPTY_EMAIL_CONFIG: EmailChannelConfig = {
  mailTo: '',
  smtpHost: '',
  smtpPort: '587',
  smtpStarttls: 'true',
  username: '',
  fromAddr: '',
  passwordEnv: 'DEEPSEEK_EMAIL_PASSWORD'
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
  return {
    mailTo: readTomlString(content, 'mail_to', { section: 'automation' }) ?? '',
    smtpHost: readTomlRaw(content, 'smtp_host', 'automation.email') ?? '',
    smtpPort: readTomlRaw(content, 'smtp_port', 'automation.email') ?? '587',
    smtpStarttls: readTomlRaw(content, 'smtp_starttls', 'automation.email') ?? 'true',
    username: readTomlRaw(content, 'username', 'automation.email') ?? '',
    fromAddr: readTomlRaw(content, 'from_addr', 'automation.email') ?? '',
    passwordEnv: readTomlRaw(content, 'password_env', 'automation.email') ?? 'DEEPSEEK_EMAIL_PASSWORD'
  }
}

export function isEmailConfigured(config: EmailChannelConfig): boolean {
  return Boolean(config.mailTo && config.smtpHost && config.username)
}
