/** Email channel presets and helpers shared by renderer + tests. */

export type EmailProviderId = '163' | 'qq' | 'gmail' | 'outlook' | 'custom'

export const EMAIL_PROVIDER_IDS = ['163', 'qq', 'gmail', 'outlook', 'custom'] as const satisfies readonly EmailProviderId[]

export type EmailProviderPreset = {
  smtpHost: string
  smtpPort: string
  smtpSsl: boolean
  smtpStarttls: boolean
}

export const EMAIL_PROVIDER_PRESETS: Record<Exclude<EmailProviderId, 'custom'>, EmailProviderPreset> =
  {
    '163': {
      smtpHost: 'smtp.163.com',
      smtpPort: '465',
      smtpSsl: true,
      smtpStarttls: false
    },
    qq: {
      smtpHost: 'smtp.qq.com',
      smtpPort: '465',
      smtpSsl: true,
      smtpStarttls: false
    },
    gmail: {
      smtpHost: 'smtp.gmail.com',
      smtpPort: '587',
      smtpSsl: false,
      smtpStarttls: true
    },
    outlook: {
      smtpHost: 'smtp.office365.com',
      smtpPort: '587',
      smtpSsl: false,
      smtpStarttls: true
    }
  }

export const DEFAULT_EMAIL_PASSWORD_ENV = 'DEEPSEEK_EMAIL_PASSWORD'

export function inferEmailProviderFromHost(host: string): EmailProviderId {
  const normalized = host.trim().toLowerCase()
  if (!normalized) return 'custom'
  if (normalized.includes('163.com')) return '163'
  if (normalized.includes('qq.com')) return 'qq'
  if (normalized.includes('gmail.com')) return 'gmail'
  if (normalized.includes('office365.com') || normalized.includes('outlook.com')) return 'outlook'
  return 'custom'
}

export function applyEmailProviderPreset(
  provider: EmailProviderId
): EmailProviderPreset | null {
  if (provider === 'custom') return null
  return EMAIL_PROVIDER_PRESETS[provider]
}

/** i18n keys for provider labels in ``common`` namespace. */
export const EMAIL_PROVIDER_LABEL_KEYS: Record<EmailProviderId, string> = {
  '163': 'channelEmailProvider163',
  qq: 'channelEmailProviderQq',
  gmail: 'channelEmailProviderGmail',
  outlook: 'channelEmailProviderOutlook',
  custom: 'channelEmailProviderCustom'
}
